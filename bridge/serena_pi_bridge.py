#!/usr/bin/env python3
"""JSONL bridge that starts SolidLSP for a given project and dispatches tool calls.

Issue #1 — init/shutdown lifecycle.
Issue #3 — find_symbol tool.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Iterator

# Ensure the vendored solidlsp (sibling directory) is importable.
_BRIDGE_DIR = Path(__file__).resolve().parent
if str(_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_DIR))

import yaml

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.ls_types import SymbolKind, UnifiedSymbolInformation
from solidlsp.settings import SolidLSPSettings

from name_path import compute_name_path, NamePathMatcher

PACKAGE_ROOT = _BRIDGE_DIR.parent
SERENA_HOME = PACKAGE_ROOT / ".serena-data"

os.environ.setdefault("SERENA_HOME", str(SERENA_HOME))


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class Bridge:
    """Bridge that can start/stop a SolidLSP language server and dispatch tool calls."""

    def __init__(self) -> None:
        self.ls: SolidLanguageServer | None = None
        self.cwd: str | None = None
        # Cache the tool contracts for validation
        self._tool_contracts: dict[str, object] | None = None

    def init(self, cwd: str) -> dict[str, object]:
        """Start a language server for *cwd*.

        Reads ``.serenaproject.yml`` to determine which language(s) to activate.
        Falls back to auto-detection (TypeScript > Python > default).
        """
        project_root = str(Path(cwd).resolve())
        languages = self._read_languages(project_root)

        if not languages:
            languages = self._detect_languages(project_root)

        if not languages:
            raise RuntimeError(
                f"No languages configured for {project_root}. "
                "Place a .serenaproject.yml with a 'languages' list in the project root."
            )

        lang = Language(languages[0])

        settings = SolidLSPSettings(
            solidlsp_dir=str(Path.home() / ".solidlsp"),
            project_data_path=str(Path(project_root) / ".solidlsp"),
        )

        config = LanguageServerConfig(
            code_language=lang,
            encoding="utf-8",
        )

        self.ls = SolidLanguageServer.create(config, project_root, solidlsp_settings=settings)
        self.ls.start()
        self.cwd = project_root

        return {"ok": True, "language": str(lang), "cwd": project_root}

    def shutdown(self) -> str:
        """Stop the language server cleanly."""
        if self.ls is not None:
            self.ls.stop()
            self.ls = None
        self.cwd = None
        return "OK"

    # -- tool dispatch -----------------------------------------------------

    def call_tool(self, tool_name: str, params: dict[str, object]) -> object:
        """Validate and dispatch a tool call."""
        if self.ls is None:
            raise RuntimeError("Bridge not initialized. Call init first.")

        contracts = self._load_tool_contracts()
        tool_contract = contracts.get(tool_name)
        if tool_contract is None:
            raise ValueError(f"Unknown tool: {tool_name}")

        self._validate_params(tool_name, params, tool_contract)

        if tool_name == "find_symbol":
            return self._find_symbol(params)
        else:
            raise ValueError(f"Tool not implemented: {tool_name}")

    def _load_tool_contracts(self) -> dict[str, dict[str, object]]:
        """Load tool-contracts.json (cached)."""
        if self._tool_contracts is not None:
            return self._tool_contracts  # type: ignore[return-value]
        contract_path = PACKAGE_ROOT / "src" / "tool-contracts.json"
        if not contract_path.is_file():
            raise FileNotFoundError(f"Tool contracts not found: {contract_path}")
        with open(contract_path, encoding="utf-8") as f:
            data = json.load(f)
        self._tool_contracts = data.get("tools", {})
        return self._tool_contracts  # type: ignore[return-value]

    @staticmethod
    def _validate_params(
        tool_name: str,
        params: dict[str, object],
        contract: dict[str, object],
    ) -> None:
        """Minimal validation: check required params are present."""
        schema = contract.get("params")
        if not isinstance(schema, dict):
            return
        required: list[str] = schema.get("required", []) or []  # type: ignore[assignment]
        for key in required:
            if key not in params:
                raise ValueError(
                    f"Tool '{tool_name}' requires parameter '{key}'"
                )

    # -- find_symbol tool --------------------------------------------------

    _RG_JSON_LINE_RE = re.compile(r"^\s*\{")

    def _find_symbol(self, params: dict[str, object]) -> dict[str, object]:
        name_path_str = str(params["name_path"])
        relative_path = params.get("relative_path")
        if relative_path is not None:
            relative_path = str(relative_path)
        code_snippet = params.get("code_snippet")
        if code_snippet is not None:
            code_snippet = str(code_snippet)
        kinds: list[int] | None = None
        raw_kinds = params.get("kinds")
        if raw_kinds is not None and isinstance(raw_kinds, list):
            kinds = [int(k) for k in raw_kinds]
        max_matches = int(params.get("max_matches", 10))

        matcher = NamePathMatcher(name_path_str)

        # 1. Get symbol tree
        assert self.ls is not None
        tree = self.ls.request_full_symbol_tree(
            within_relative_path=relative_path if relative_path else None
        )

        # 2. Flatten and match
        flat_symbols = list(self._flatten_tree(tree))

        matched: list[UnifiedSymbolInformation] = []
        for sym in flat_symbols:
            np = compute_name_path(sym)
            if matcher.matches(np):
                matched.append(sym)

        # 3. Filter by code_snippet (rg)
        if code_snippet is not None:
            matched = self._filter_by_snippet(
                matched, code_snippet,
                within_path=str(relative_path) if relative_path else None,
            )

        # 4. Filter by kinds
        if kinds is not None:
            kinds_set = set(kinds)
            matched = [s for s in matched if s["kind"] in kinds_set]

        # 5. Cap at max_matches (-1 = unlimited)
        if max_matches == -1:
            truncated = False
        else:
            truncated = len(matched) > max_matches
            if truncated:
                matched = matched[:max_matches]

        # 6. Format output
        result_symbols: list[dict[str, object]] = []
        for sym in matched:
            np = compute_name_path(sym)
            kind_name = SymbolKind(sym["kind"]).name
            loc_str = self._format_location(sym)
            result_symbols.append({
                "name_path": np,
                "kind": kind_name,
                "location": loc_str,
            })

        return {
            "symbols": result_symbols,
            "truncated": truncated,
        }

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _flatten_tree(
        symbols: list[UnifiedSymbolInformation],
    ) -> "Iterator[UnifiedSymbolInformation]":
        """Recursively yield all symbols in the tree (pre-order)."""
        for sym in symbols:
            yield sym
            children = sym.get("children", [])
            if children:
                yield from Bridge._flatten_tree(children)

    @staticmethod
    def _format_location(sym: UnifiedSymbolInformation) -> str:
        """Format a compact location string: ``rel/path:startLine-endLine``."""
        loc = sym.get("location")
        if loc is None:
            return "unknown:0-0"
        rel = loc.get("relativePath") or "unknown"
        rng = loc.get("range")
        if rng is None:
            return f"{rel}:0-0"
        start_line = rng["start"]["line"]
        end_line = rng["end"]["line"]
        return f"{rel}:{start_line}-{end_line}"

    def _filter_by_snippet(
        self,
        symbols: list[UnifiedSymbolInformation],
        snippet: str,
        within_path: str | None,
    ) -> list[UnifiedSymbolInformation]:
        """Run ``rg --json`` for *snippet* and keep only symbols whose
        location falls within a snippet occurrence."""
        assert self.cwd is not None

        # Build rg command
        cmd = ["rg", "--json", "-F"]
        # Use multiline if snippet contains newlines
        if "\n" in snippet:
            cmd.append("--multiline")
        cmd.extend(["-e", snippet])
        # Scope path
        if within_path is not None:
            cmd.append(within_path)

        try:
            proc = subprocess.run(
                cmd,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise RuntimeError(f"rg command failed: {exc}") from exc

        # Parse JSON lines from stdout (rg --json outputs one JSON object per line)
        occurrences: list[tuple[str, int, int]] = []  # (relative_path, start_line, end_line)
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            if not self._RG_JSON_LINE_RE.match(line):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "match":
                continue
            data = obj.get("data")
            if not isinstance(data, dict):
                continue
            path_info = data.get("path")
            if not isinstance(path_info, dict):
                continue
            file_path = path_info.get("text")
            if not isinstance(file_path, str):
                continue
            line_num = data.get("line_number")
            if not isinstance(line_num, int):
                continue
            # Determine end line: count newlines in the matched text
            lines_data = data.get("lines")
            if isinstance(lines_data, dict):
                text = lines_data.get("text", "")
                num_lines = text.count("\n") + 1 if text else 1
            else:
                num_lines = 1
            start_line = line_num - 1  # rg line numbers are 1-based
            end_line = start_line + num_lines - 1
            occurrences.append((file_path, start_line, end_line))

        if not occurrences:
            return []

        # Build lookup: relative_path -> set of line ranges
        occ_map: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for fp, sl, el in occurrences:
            # Normalize path (rg may return ./prefix or bare)
            normalized = fp.lstrip("./") or "."
            occ_map[normalized].append((sl, el))

        # Filter symbols
        result: list[UnifiedSymbolInformation] = []
        for sym in symbols:
            loc = sym.get("location")
            if loc is None:
                continue
            rel = loc.get("relativePath")
            if rel is None:
                continue
            rng = loc.get("range")
            if rng is None:
                continue
            sym_start = rng["start"]["line"]
            sym_end = rng["end"]["line"]

            rel_norm = str(rel).lstrip("./") or "."
            for occ_start, occ_end in occ_map.get(rel_norm, []):
                # Check if symbol range overlaps with occurrence range
                if sym_start >= occ_start and sym_end <= occ_end:
                    result.append(sym)
                    break

        return result

    @staticmethod
    def _read_languages(project_root: str) -> list[str]:
        config_path = Path(project_root) / ".serenaproject.yml"
        if not config_path.is_file():
            return []
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg: object = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise RuntimeError(f"Invalid YAML in {config_path}: {exc}") from exc
        if not isinstance(cfg, dict):
            return []
        return cfg.get("languages", []) or []

    @staticmethod
    def _detect_languages(project_root: str) -> list[str]:
        root = Path(project_root)
        # TypeScript
        if (list(root.glob("tsconfig.json"))
                or list(root.glob("*.ts"))
                or list(root.glob("src/**/*.ts"))
                or list(root.glob("*.tsx"))
                or list(root.glob("src/**/*.tsx"))):
            return ["typescript"]
        # Python
        if (list(root.glob("*.py"))
                or list(root.glob("src/**/*.py"))
                or list(root.glob("pyproject.toml"))
                or list(root.glob("setup.py"))
                or list(root.glob("setup.cfg"))):
            return ["python"]
        return ["typescript"]  # safe default


# ---------------------------------------------------------------------------
# JSONL protocol helpers
# ---------------------------------------------------------------------------


def respond(
    request_id: object,
    ok: bool,
    result: object = None,
    error: str | None = None,
) -> None:
    payload: dict[str, object] = {"id": request_id, "ok": ok}
    if ok:
        payload["result"] = result
    else:
        payload["error"] = {
            "kind": "error",
            "message": error or "Unknown error",
        }
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
            elif method == "shutdown":
                result = bridge.shutdown()
                respond(request_id, True, result)
                return 0
            elif method == "call_tool":
                tool_name = str(request["tool_name"])
                # Build params dict from remaining fields
                params = {
                    k: v
                    for k, v in request.items()
                    if k not in ("id", "method", "tool_name")
                }
                result = bridge.call_tool(tool_name, params)
            else:
                raise ValueError(f"Unknown method: {method}")

            respond(request_id, True, result)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            try:
                respond(
                    request_id,
                    False,
                    error=f"{exc.__class__.__name__}: {exc}",
                )
            except Exception:
                pass  # broken pipe — process will exit anyway
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
