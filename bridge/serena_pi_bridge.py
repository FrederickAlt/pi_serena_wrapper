#!/usr/bin/env python3
"""JSONL bridge exposing a small Serena LSP tool set to pi extensions."""

from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import traceback
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
VENDOR_SRC = PACKAGE_ROOT / "vendor" / "serena" / "src"
SERENA_HOME = PACKAGE_ROOT / ".serena-data"
PROJECT_DATA_ROOT = PACKAGE_ROOT / ".serena-projects"
FAILED_TOOL_LOG = SERENA_HOME / "failed-tool-calls.jsonl"

os.environ.setdefault("SERENA_HOME", str(SERENA_HOME))
os.environ.setdefault("SERENA_USAGE_REPORTING", "false")
sys.path.insert(0, str(VENDOR_SRC))

NATIVE_TOOL_NAMES = {
    "get_symbols_overview",
    "find_symbol",
    "find_referencing_symbols",
    "rename_symbol",
}

EXPOSED_TOOL_NAMES = [
    "get_symbols_overview",
    "find_symbol",
    "find_referencing_symbols",
    "find_declaration",
    "find_implementations",
    "rename_symbol",
]


class Bridge:
    def __init__(self) -> None:
        self.agent: Any | None = None
        self.cwd: str | None = None

    def init(self, cwd: str) -> dict[str, Any]:
        try:
            from serena.agent import SerenaAgent
            from serena.config.serena_config import LanguageBackend, SerenaConfig
        except Exception as exc:
            raise RuntimeError(
                "Could not import Serena. Run: "
                f"cd {PACKAGE_ROOT} && python3 -m venv .venv && .venv/bin/pip install -e vendor/serena"
            ) from exc

        project_root = str(Path(cwd).resolve())
        SERENA_HOME.mkdir(parents=True, exist_ok=True)
        PROJECT_DATA_ROOT.mkdir(parents=True, exist_ok=True)
        project_data = self._project_data_path(project_root)

        config = SerenaConfig(
            gui_log_window=False,
            web_dashboard=False,
            web_dashboard_open_on_launch=False,
            language_backend=LanguageBackend.LSP,
            default_modes=(),
            fixed_tools=tuple(NATIVE_TOOL_NAMES),
            project_serena_folder_location=str(project_data),
        )
        self.agent = SerenaAgent(project=project_root, serena_config=config)
        self.cwd = project_root
        return {"cwd": project_root, "tools": EXPOSED_TOOL_NAMES}

    @staticmethod
    def _project_data_path(project_root: str) -> Path:
        digest = hashlib.sha256(project_root.encode("utf-8")).hexdigest()[:12]
        folder_name = Path(project_root).name or "project"
        return PROJECT_DATA_ROOT / f"{folder_name}-{digest}"

    def list_tools(self) -> list[str]:
        self._agent()
        return EXPOSED_TOOL_NAMES

    def call_tool(self, tool: str, args: dict[str, Any]) -> Any:
        if tool not in EXPOSED_TOOL_NAMES:
            raise ValueError(f"Unknown Serena pi tool: {tool}")
        try:
            if tool in NATIVE_TOOL_NAMES:
                result = self._agent().get_tool_by_name(tool).apply_ex(**args)
            elif tool == "find_declaration":
                result = self._run_agent_task(lambda: self.find_declaration(**args), tool)
            elif tool == "find_implementations":
                result = self._run_agent_task(lambda: self.find_implementations(**args), tool)
            else:
                raise AssertionError(f"Unhandled tool: {tool}")
        except Exception as exc:
            self._log_failed_tool_call(tool, args, "exception", f"{exc.__class__.__name__}: {exc}")
            raise

        failure_message = self._result_failure_message(result)
        if failure_message is not None:
            self._log_failed_tool_call(tool, args, "error_result", failure_message, result)
        return result

    def shutdown(self) -> str:
        if self.agent is not None:
            self.agent.on_shutdown()
            self.agent = None
        return "OK"

    def find_declaration(
        self,
        relative_path: str,
        regex: str | None = None,
        code_snippet: str | None = None,
        symbol_text: str | None = None,
        occurrence_index: int | None = None,
        name_path: str | None = None,
        line: int | None = None,
        column: int | None = None,
        include_body: bool = False,
    ) -> str:
        retriever = self._symbol_retriever()
        if name_path is not None:
            symbol = retriever.find_unique(name_path, within_relative_path=relative_path)
            return self._json(symbol.to_dict(kind=True, name_path=True, relative_path=True, body_location=True, body=include_body))

        line, column = self._resolve_position(
            relative_path,
            regex=regex,
            code_snippet=code_snippet,
            symbol_text=symbol_text,
            occurrence_index=occurrence_index,
            line=line,
            column=column,
        )
        lang_server = retriever.get_language_server(relative_path)
        symbol = lang_server.request_defining_symbol(relative_path, line, column, include_body=include_body)
        if symbol is None:
            locations = lang_server.request_definition(relative_path, line, column)
            return self._json(locations)
        return self._json(symbol)

    def find_implementations(
        self,
        relative_path: str,
        name_path: str | None = None,
        line: int | None = None,
        column: int | None = None,
        include_body: bool = False,
    ) -> str:
        retriever = self._symbol_retriever()
        if name_path is not None:
            symbol = retriever.find_unique(name_path, within_relative_path=relative_path)
            if symbol.line is None or symbol.column is None:
                raise ValueError(f"Symbol {name_path} has no LSP position.")
            line = symbol.line
            column = symbol.column
        if line is None or column is None:
            raise ValueError("find_implementations requires name_path or line and column.")

        lang_server = retriever.get_language_server(relative_path)
        symbols = lang_server.request_implementing_symbols(relative_path, line, column, include_body=include_body)
        if not symbols:
            return self._json(lang_server.request_implementation(relative_path, line, column))
        return self._json(symbols)

    def _resolve_position(
        self,
        relative_path: str,
        *,
        regex: str | None,
        code_snippet: str | None,
        symbol_text: str | None,
        occurrence_index: int | None,
        line: int | None,
        column: int | None,
    ) -> tuple[int, int]:
        if line is not None and column is not None:
            return line, column
        if regex is None and code_snippet is None:
            raise ValueError("A regex with one capture group, code_snippet, or line and column is required.")

        path = Path(self._agent().get_active_project_or_raise().project_root) / relative_path
        content = path.read_text(encoding="utf-8")

        if code_snippet is not None:
            offset = self._resolve_code_snippet_offset(content, code_snippet, symbol_text, occurrence_index)
        else:
            assert regex is not None
            try:
                matches = list(re.finditer(regex, content, flags=re.MULTILINE | re.DOTALL))
            except re.error as exc:
                raise ValueError(
                    f"Invalid regex for find_declaration: {exc}. "
                    "Prefer code_snippet plus symbol_text to avoid escaping issues."
                ) from exc
            match = self._select_position_match(matches, occurrence_index, "regex", content)
            if len(match.groups()) != 1:
                raise ValueError(
                    f"Expected regex to contain exactly one capture group, got {len(match.groups())}. "
                    "The capture group marks the exact symbol occurrence for the LSP cursor. "
                    "Prefer code_snippet plus symbol_text if regex escaping is awkward."
                )
            offset = match.start(1)

        before = content[:offset]
        resolved_line = before.count("\n")
        last_newline = before.rfind("\n")
        resolved_col = offset if last_newline == -1 else offset - last_newline - 1
        return resolved_line, resolved_col

    @staticmethod
    def _resolve_code_snippet_offset(content: str, code_snippet: str, symbol_text: str | None, occurrence_index: int | None) -> int:
        starts = Bridge._find_all_offsets(content, code_snippet)
        start = Bridge._select_offset(starts, occurrence_index, "code_snippet", content)

        if symbol_text is None:
            return start
        target_start = code_snippet.find(symbol_text)
        if target_start == -1:
            raise ValueError("symbol_text was not found inside code_snippet.")
        if code_snippet.find(symbol_text, target_start + 1) != -1:
            raise ValueError("symbol_text must occur exactly once inside code_snippet. Use a smaller code_snippet around the symbol if needed.")
        return start + target_start

    @staticmethod
    def _find_all_offsets(content: str, needle: str) -> list[int]:
        if not needle:
            raise ValueError("code_snippet must not be empty.")
        starts: list[int] = []
        start = content.find(needle)
        while start != -1:
            starts.append(start)
            start = content.find(needle, start + 1)
        return starts

    @staticmethod
    def _select_position_match(matches: list[re.Match[str]], occurrence_index: int | None, label: str, content: str) -> re.Match[str]:
        offset = Bridge._select_offset([match.start(0) for match in matches], occurrence_index, label, content)
        for match in matches:
            if match.start(0) == offset:
                return match
        raise AssertionError("Selected offset did not correspond to a regex match.")

    @staticmethod
    def _select_offset(starts: list[int], occurrence_index: int | None, label: str, content: str) -> int:
        if occurrence_index is not None:
            if occurrence_index < 0:
                raise ValueError("occurrence_index must be 0 or greater.")
            if occurrence_index >= len(starts):
                raise ValueError(f"{label} matched {len(starts)} occurrence(s), so occurrence_index {occurrence_index} is out of range.")
            return starts[occurrence_index]

        if len(starts) == 1:
            return starts[0]
        if len(starts) == 0:
            raise ValueError(f"Expected {label} to match exactly once, got 0 matches.")

        occurrences = Bridge._format_occurrences(content, starts)
        raise ValueError(
            f"Expected {label} to match exactly once, got {len(starts)} matches. "
            "Provide a longer unique code_snippet or set occurrence_index to one of these 0-based occurrences:\n"
            f"{occurrences}"
        )

    @staticmethod
    def _format_occurrences(content: str, starts: list[int]) -> str:
        lines = []
        for index, start in enumerate(starts[:10]):
            line, col = Bridge._line_col_for_offset(content, start)
            snippet = Bridge._line_snippet_for_offset(content, start)
            lines.append(f"{index}: line {line}, column {col}: {snippet}")
        if len(starts) > 10:
            lines.append(f"... {len(starts) - 10} more occurrences")
        return "\n".join(lines)

    @staticmethod
    def _line_col_for_offset(content: str, offset: int) -> tuple[int, int]:
        before = content[:offset]
        line = before.count("\n")
        last_newline = before.rfind("\n")
        col = offset if last_newline == -1 else offset - last_newline - 1
        return line, col

    @staticmethod
    def _line_snippet_for_offset(content: str, offset: int) -> str:
        line_start = content.rfind("\n", 0, offset) + 1
        line_end = content.find("\n", offset)
        if line_end == -1:
            line_end = len(content)
        return content[line_start:line_end].strip()

    def _symbol_retriever(self) -> Any:
        from serena.symbol import LanguageServerSymbolRetriever

        return LanguageServerSymbolRetriever(self._agent().get_active_project_or_raise())

    def _agent(self) -> Any:
        if self.agent is None:
            raise RuntimeError("Bridge has not been initialized. Call init first.")
        return self.agent

    def _run_agent_task(self, fn: Any, name: str) -> Any:
        agent = self._agent()
        task = agent.issue_task(fn, name=f"Pi{name}")
        return task.result(timeout=agent.serena_config.tool_timeout)

    def _log_failed_tool_call(
        self,
        tool: str,
        args: dict[str, Any],
        failure_kind: str,
        message: str,
        result: Any | None = None,
    ) -> None:
        try:
            SERENA_HOME.mkdir(parents=True, exist_ok=True)
            entry: dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cwd": self.cwd,
                "tool": tool,
                "args": self._jsonable(args),
                "failure_kind": failure_kind,
                "message": message,
            }
            if result is not None:
                entry["result_excerpt"] = str(result)[:4000]
            with FAILED_TOOL_LOG.open("a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception:
            traceback.print_exc(file=sys.stderr)

    @staticmethod
    def _result_failure_message(result: Any) -> str | None:
        if not isinstance(result, str):
            return None
        stripped = result.strip()
        if stripped.startswith("Error:") or stripped.startswith("Error executing tool:"):
            return stripped.splitlines()[0]
        return None

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(Bridge._jsonable(value), ensure_ascii=False, default=str)

    @staticmethod
    def _jsonable(value: Any, seen: set[int] | None = None) -> Any:
        if seen is None:
            seen = set()
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (list, tuple, set)):
            return [Bridge._jsonable(item, seen) for item in value]
        if isinstance(value, dict):
            obj_id = id(value)
            if obj_id in seen:
                return "<circular>"
            seen.add(obj_id)
            try:
                return {
                    str(key): Bridge._jsonable(item, seen)
                    for key, item in value.items()
                    if str(key) not in {"parent", "parentSymbol"}
                }
            finally:
                seen.remove(obj_id)
        return str(value)


def respond(request_id: Any, ok: bool, result: Any = None, error: str | None = None) -> None:
    payload: dict[str, Any] = {"id": request_id, "ok": ok}
    if ok:
        payload["result"] = result
    else:
        payload["error"] = error
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main() -> int:
    bridge = Bridge()
    for line in sys.stdin:
        if not line.strip():
            continue
        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            method = request.get("method")
            if method == "init":
                result = bridge.init(str(request["cwd"]))
            elif method == "list_tools":
                result = bridge.list_tools()
            elif method == "call_tool":
                result = bridge.call_tool(str(request["tool"]), dict(request.get("args") or {}))
            elif method == "shutdown":
                result = bridge.shutdown()
                respond(request_id, True, result)
                return 0
            else:
                raise ValueError(f"Unknown method: {method}")
            respond(request_id, True, result)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            respond(request_id, False, error=f"{exc.__class__.__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
