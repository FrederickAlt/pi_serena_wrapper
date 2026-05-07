#!/usr/bin/env python3
"""JSONL bridge exposing a small Serena LSP tool set to pi extensions."""

from __future__ import annotations

import json
import hashlib
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
import os
import sys
import traceback
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SERENA_HOME = PACKAGE_ROOT / ".serena-data"
PROJECT_DATA_ROOT = PACKAGE_ROOT / ".serena-projects"
FAILED_TOOL_LOG = SERENA_HOME / "failed-tool-calls.jsonl"

os.environ.setdefault("SERENA_HOME", str(SERENA_HOME))
os.environ.setdefault("SERENA_USAGE_REPORTING", "false")

NATIVE_TOOL_NAMES = {
    "get_symbols_overview",
    "find_symbol",
    "find_referencing_symbols",
}

NATIVE_UNTRUNCATED_READ_TOOL_NAMES = {
    "get_symbols_overview",
    "find_symbol",
}

EXPOSED_TOOL_NAMES = [
    "get_symbols_overview",
    "find_symbol",
    "get_symbol_from_snippet",
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
            serena_version = self._validate_serena_install()
            agent_module = import_module("serena.agent")
            config_module = import_module("serena.config.serena_config")
            SerenaAgent = agent_module.SerenaAgent
            LanguageBackend = config_module.LanguageBackend
            SerenaConfig = config_module.SerenaConfig
        except Exception as exc:
            raise RuntimeError(
                "Could not import a compatible pip-installed Serena package. Run: "
                f"cd {PACKAGE_ROOT} && python3 -m venv .venv && .venv/bin/pip install --upgrade serena-agent"
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
        return {"cwd": project_root, "tools": EXPOSED_TOOL_NAMES, "serena_agent_version": serena_version}

    @staticmethod
    def _validate_serena_install() -> str:
        try:
            serena_version = version("serena-agent")
        except PackageNotFoundError as exc:
            raise RuntimeError("Python distribution serena-agent is not installed.") from exc

        required_members = {
            "serena.agent": ("SerenaAgent",),
            "serena.config.serena_config": ("LanguageBackend", "SerenaConfig"),
            "serena.symbol": ("LanguageServerSymbolRetriever",),
            "solidlsp": (),
            "interprompt": (),
        }
        for module_name, members in required_members.items():
            try:
                module = import_module(module_name)
            except Exception as exc:
                raise RuntimeError(
                    f"Installed serena-agent {serena_version} is incompatible: cannot import {module_name}."
                ) from exc
            for member in members:
                if not hasattr(module, member):
                    raise RuntimeError(
                        f"Installed serena-agent {serena_version} is incompatible: {module_name}.{member} is missing."
                    )

        return serena_version

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
            if tool == "get_symbols_overview":
                result = self._agent().get_tool_by_name(tool).apply_ex(max_answer_chars=-1, **args)
            elif tool == "find_symbol":
                result = self.find_symbol(**args)
            elif tool == "get_symbol_from_snippet":
                result = self._run_agent_task(lambda: self.get_symbol_from_snippet(**args), tool)
            elif tool == "find_declaration":
                result = self._run_agent_task(lambda: self.find_declaration(**args), tool)
            elif tool == "find_implementations":
                result = self._run_agent_task(lambda: self.find_implementations(**args), tool)
            elif tool == "find_referencing_symbols":
                result = self._run_agent_task(lambda: self.find_referencing_symbols(**args), tool)
            elif tool == "rename_symbol":
                result = self._run_agent_task(lambda: self.rename_symbol(**args), tool)
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

    def find_symbol(
        self,
        name_path_pattern: str,
        depth: int = 0,
        relative_path: str = "",
        kinds: list[int] | None = None,
        max_matches: int = -1,
    ) -> str:
        return self._agent().get_tool_by_name("find_symbol").apply_ex(
            name_path_pattern=name_path_pattern,
            depth=depth,
            relative_path=relative_path,
            include_body=False,
            include_info=False,
            include_kinds=kinds or [],
            exclude_kinds=[],
            substring_matching=False,
            max_matches=max_matches,
            max_answer_chars=-1,
        )

    def get_symbol_from_snippet(
        self,
        relative_path: str,
        code_snippet: str,
        symbol_text: str,
        resolve: str = "declaration",
        line: int | None = None,
        column: int | None = None,
    ) -> str:
        if resolve not in {"declaration", "type_definition"}:
            raise ValueError("resolve must be either 'declaration' or 'type_definition'.")

        positions = self._resolve_all_source_positions(relative_path, code_snippet, symbol_text, line, column)
        retriever = self._symbol_retriever()
        lang_server = retriever.get_language_server(relative_path)
        matches: list[dict[str, Any]] = []
        raw_locations: list[Any] = []
        for line, column in positions:
            if resolve == "declaration":
                symbol = lang_server.request_defining_symbol(relative_path, line, column, include_body=False)
                if symbol is None:
                    locations = lang_server.request_definition(relative_path, line, column)
                    raw_locations.extend(locations)
                    matches.extend(self._symbol_references_for_locations(lang_server, locations))
                else:
                    matches.append(self._symbol_reference_from_lsp_symbol(symbol))
            else:
                locations = self._request_type_definition_locations(lang_server, relative_path, line, column)
                raw_locations.extend(locations)
                matches.extend(self._symbol_references_for_locations(lang_server, locations))

        deduped_matches = self._dedupe_symbol_references(matches)
        result: dict[str, Any] = {"matches": deduped_matches}
        if not deduped_matches:
            deduped_locations = self._dedupe_locations(raw_locations)
            if deduped_locations:
                result["locations"] = deduped_locations
                result["unresolved"] = {
                    "reason": "external_or_unindexed_target",
                    "message": "The language server resolved this occurrence, but the target could not be converted to a Serena project symbol.",
                }
            else:
                result["unresolved"] = {
                    "reason": "no_lsp_target",
                    "message": "The language server did not return a declaration or type definition for this occurrence.",
                }
        return self._json(result)

    def find_declaration(
        self,
        relative_path: str,
        name_path: str,
    ) -> str:
        symbol = self._resolve_unique_symbol(name_path, relative_path)
        if symbol.line is None or symbol.column is None:
            raise ValueError(f"Symbol {name_path} has no LSP position.")
        lang_server = self._symbol_retriever().get_language_server(symbol.relative_path or relative_path)
        symbol_result = lang_server.request_defining_symbol(symbol.relative_path or relative_path, symbol.line, symbol.column, include_body=False)
        locations: list[Any] = []
        if symbol_result is None:
            locations = lang_server.request_definition(symbol.relative_path or relative_path, symbol.line, symbol.column)
            symbols = self._symbol_references_for_locations(lang_server, locations)
        else:
            symbols = [self._symbol_reference_from_lsp_symbol(symbol_result)]
        if not symbols:
            symbols = [self._symbol_reference_from_serena_symbol(symbol)]
        result: dict[str, Any] = {"symbols": symbols}
        if locations and not symbols:
            result["locations"] = locations
        return self._json(result)

    def find_referencing_symbols(
        self,
        relative_path: str,
        name_path: str,
        kinds: list[int] | None = None,
    ) -> str:
        symbol = self._resolve_unique_symbol(name_path, relative_path)
        from solidlsp.ls_types import SymbolKind

        include_kinds = [SymbolKind(k) for k in kinds] if kinds else None
        references = self._symbol_retriever().find_referencing_symbols_by_location(
            symbol.location,
            include_body=False,
            include_kinds=include_kinds,
            exclude_kinds=None,
        )
        return self._json(self._reference_results_by_file(references))

    def find_implementations(
        self,
        relative_path: str,
        name_path: str,
    ) -> str:
        symbol = self._resolve_unique_symbol(name_path, relative_path)
        if symbol.line is None or symbol.column is None:
            raise ValueError(f"Symbol {name_path} has no LSP position.")
        symbol_relative_path = symbol.relative_path or relative_path
        lang_server = self._symbol_retriever().get_language_server(symbol_relative_path)
        try:
            symbols = lang_server.request_implementing_symbols(symbol_relative_path, symbol.line, symbol.column, include_body=False)
        except Exception as exc:
            if self._is_unsupported_lsp_method(exc, "textDocument/implementation"):
                return (
                    "Error: find_implementations is not supported by the active language server "
                    f"for {symbol_relative_path}. The language server does not support textDocument/implementation."
                )
            raise
        if symbols:
            return self._json({"symbols": [self._symbol_reference_from_lsp_symbol(s) for s in symbols]})
        locations = lang_server.request_implementation(symbol_relative_path, symbol.line, symbol.column)
        return self._json({"symbols": self._symbol_references_for_locations(lang_server, locations), "locations": locations})

    def rename_symbol(
        self,
        relative_path: str,
        name_path: str,
        new_name: str,
    ) -> str:
        symbol = self._resolve_unique_symbol(name_path, relative_path)
        from serena.code_editor import LanguageServerCodeEditor

        return LanguageServerCodeEditor(self._symbol_retriever()).rename_symbol(
            symbol.get_name_path(),
            symbol.relative_path or relative_path,
            new_name,
        )

    def _resolve_unique_symbol(self, name_path: str, relative_path: str) -> Any:
        retriever = self._symbol_retriever()
        candidates = retriever.find(name_path, substring_matching=False, within_relative_path=relative_path)
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) == 0:
            raise ValueError(f"No symbol matching '{name_path}' found")

        exact_matches = [s for s in candidates if s.get_name_path() == name_path]
        if len(exact_matches) == 1:
            return exact_matches[0]

        raise ValueError(
            f"Found multiple {len(candidates)} symbols matching '{name_path}'. "
            "They are: \n" + self._json([self._symbol_reference_from_serena_symbol(s) for s in candidates])
        )

    @staticmethod
    def _symbol_reference_from_serena_symbol(symbol: Any) -> dict[str, Any]:
        return symbol.to_dict(kind=True, name_path=True, relative_path=True, body_location=True, depth=0, body=False)

    @staticmethod
    def _symbol_reference_from_lsp_symbol(symbol: Any) -> dict[str, Any]:
        from serena.symbol import LanguageServerSymbol

        if hasattr(symbol, "to_dict"):
            return Bridge._symbol_reference_from_serena_symbol(symbol)
        return LanguageServerSymbol(symbol).to_dict(kind=True, name_path=True, relative_path=True, body_location=True, depth=0, body=False)

    def _symbol_references_for_locations(self, lang_server: Any, locations: list[Any]) -> list[dict[str, Any]]:
        return [self._symbol_reference_from_lsp_symbol(s) for s in self._symbols_for_locations(lang_server, locations)]

    @staticmethod
    def _dedupe_symbol_references(symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str | None, str | None, str | None]] = set()
        for symbol in symbols:
            key = (
                symbol.get("relative_path"),
                symbol.get("name_path"),
                symbol.get("kind"),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(symbol)
        return deduped

    @staticmethod
    def _dedupe_locations(locations: list[Any]) -> list[Any]:
        deduped: list[Any] = []
        seen: set[str] = set()
        for location in locations:
            key = json.dumps(Bridge._jsonable(location), sort_keys=True, ensure_ascii=False, default=str)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(location)
        return deduped

    def _reference_results_by_file(self, references: list[Any]) -> dict[str, dict[str, list[dict[str, Any]]]]:
        grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
        project = self._agent().get_active_project_or_raise()
        for ref in references:
            ref_dict = ref.symbol.to_dict(kind=True, relative_path=True, depth=0, body=False, body_location=True)
            ref_relative_path = ref.symbol.location.relative_path
            if ref_relative_path is None:
                continue
            content_around_ref = project.retrieve_content_around_line(
                relative_file_path=ref_relative_path,
                line=ref.line,
                context_lines_before=1,
                context_lines_after=1,
            )
            ref_dict["content_around_reference"] = content_around_ref.to_display_string()
            grouped.setdefault(ref_relative_path, {}).setdefault(str(ref_dict.get("kind", "Unknown")), []).append(ref_dict)
        return grouped

    def _resolve_all_source_positions(
        self,
        relative_path: str,
        code_snippet: str,
        symbol_text: str,
        line: int | None = None,
        column: int | None = None,
    ) -> list[tuple[int, int]]:
        path = Path(self._agent().get_active_project_or_raise().project_root) / relative_path
        content = path.read_text(encoding="utf-8")
        starts = self._find_all_offsets(content, code_snippet)
        positions: list[tuple[int, int]] = []
        for start in starts:
            target_start = code_snippet.find(symbol_text)
            if target_start == -1:
                raise ValueError("symbol_text was not found inside code_snippet.")
            if code_snippet.find(symbol_text, target_start + 1) != -1:
                raise ValueError("symbol_text must occur exactly once inside code_snippet. Use a smaller code_snippet around the symbol if needed.")
            snippet_start_line, snippet_start_col = self._line_col_for_offset(content, start)
            snippet_end_line, snippet_end_col = self._line_col_for_offset(content, start + len(code_snippet))
            symbol_offset = start + target_start
            symbol_line, symbol_col = self._line_col_for_offset(content, symbol_offset)
            symbol_end_line, symbol_end_col = self._line_col_for_offset(content, symbol_offset + len(symbol_text))
            if line is not None and not self._position_spans_line(
                snippet_start_line,
                snippet_end_line,
                line,
            ):
                continue
            if column is not None:
                if line is None:
                    raise ValueError("line must be provided when column is provided.")
                if not self._position_contains_line_column(symbol_line, symbol_col, symbol_end_line, symbol_end_col, line, column):
                    continue
            positions.append((symbol_line, symbol_col))
        if not positions:
            if line is not None or column is not None:
                raise ValueError("code_snippet was found, but no occurrence matched the provided line/column filters.")
            raise ValueError("No source positions were resolved from code_snippet and symbol_text.")
        return positions

    @staticmethod
    def _position_spans_line(start_line: int, end_line: int, line: int) -> bool:
        return start_line <= line <= end_line

    @staticmethod
    def _position_contains_line_column(
        start_line: int,
        start_col: int,
        end_line: int,
        end_col: int,
        line: int,
        column: int,
    ) -> bool:
        if line < start_line or line > end_line:
            return False
        if start_line == end_line:
            return start_col <= column < end_col
        if line == start_line:
            return column >= start_col
        if line == end_line:
            return column < end_col
        return True

    @staticmethod
    def _find_all_offsets(content: str, needle: str) -> list[int]:
        if not needle:
            raise ValueError("code_snippet must not be empty.")
        starts: list[int] = []
        start = content.find(needle)
        while start != -1:
            starts.append(start)
            start = content.find(needle, start + 1)
        if not starts:
            raise ValueError("code_snippet was not found in relative_path.")
        return starts

    @staticmethod
    def _line_col_for_offset(content: str, offset: int) -> tuple[int, int]:
        before = content[:offset]
        line = before.count("\n")
        last_newline = before.rfind("\n")
        col = offset if last_newline == -1 else offset - last_newline - 1
        return line, col

    @staticmethod
    def _request_type_definition_locations(lang_server: Any, relative_path: str, line: int, column: int) -> list[Any]:
        if not lang_server.server_started:
            raise RuntimeError("Language Server not started")

        request = lang_server.DefinitionLocationRequest(
            lang_server,
            relative_path,
            line,
            column,
            request_name="request_type_definition",
        )
        with lang_server.open_file(relative_path):
            lang_server._wait_for_cross_file_references_if_needed()
            response = lang_server.server.send.type_definition(
                lang_server._create_text_document_position_params(relative_path, line, column)
            )
        return request.normalize_response(response)

    @staticmethod
    def _symbols_for_locations(lang_server: Any, locations: list[Any]) -> list[Any]:
        symbols = []
        seen: set[tuple[str, int, int, int]] = set()
        for location in locations:
            relative_path = location.get("relativePath")
            location_range = location.get("range")
            if relative_path is None or location_range is None:
                continue
            start = location_range["start"]
            symbol = lang_server._request_symbol_at_location(
                relative_path,
                start["line"],
                start["character"],
                include_body=False,
                body_factory=None,
            )
            if symbol is None or "location" not in symbol:
                continue
            symbol_location = symbol["location"]
            symbol_key = (
                str(symbol_location["relativePath"]),
                symbol_location["range"]["start"]["line"],
                symbol_location["range"]["start"]["character"],
                int(symbol["kind"]),
            )
            if symbol_key in seen:
                continue
            seen.add(symbol_key)
            symbols.append(symbol)
        return symbols

    @staticmethod
    def _is_unsupported_lsp_method(error: Exception, method: str) -> bool:
        text = f"{error}"
        cause = getattr(error, "__cause__", None)
        while cause is not None:
            text += f"\n{cause}"
            cause = getattr(cause, "__cause__", None)
        return method in text and ("Unhandled method" in text or "-32601" in text)

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
