#!/usr/bin/env python3
"""JSONL bridge that starts SolidLSP for a given project and dispatches tool calls.

Issue #1 — init/shutdown lifecycle.
Issue #3 — find_symbol tool.
Issue #5 — get_type tool.
Issue #6 — get_references tool.
Issue #7 — get_implementations tool.
Issue #8 — get_docstring tool.
Issue #9 — rename_symbol tool.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import traceback
import urllib.parse
from collections import defaultdict
from pathlib import Path
from typing import Iterator

# Ensure the vendored solidlsp (sibling directory) is importable.
_BRIDGE_DIR = Path(__file__).resolve().parent
if str(_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_DIR))

import jsonschema
import yaml

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.ls_types import SymbolKind, UnifiedSymbolInformation
from solidlsp.lsp_protocol_handler.server import LSPError
from solidlsp.settings import SolidLSPSettings
from solidlsp.ls_utils import PathUtils

from name_path import (
    _is_dot_path,
    compute_name_path,
    NamePathMatcher,
    resolve_unique_symbol,
    resolve_unique_symbol_via_workspace,
    SymbolResolutionError,
)

from import_parser import parse_imports

PACKAGE_ROOT = _BRIDGE_DIR.parent


def _resolve_python_module(file_dir: str, module: str) -> str:
    """Resolve a Python-style relative module specifier to a filesystem path.

    Python relative imports use leading dots for depth and dots as module
    separators: ``.utils`` (same package), ``..src.utils`` (parent → src/utils).

    Returns a normalized relative path (e.g. ``src/utils``).
    """
    # Count leading dots
    depth = 0
    rest = module
    while rest.startswith("."):
        depth += 1
        rest = rest[1:]

    # Convert remaining dots to path separators
    module_path = rest.replace(".", "/") if rest else ""

    # Go up (depth - 1) levels from file_dir (. = same dir, .. = one up)
    up = file_dir
    for _ in range(depth - 1):
        up = os.path.dirname(up) or "."

    # Join and normalize
    if module_path:
        return os.path.normpath(os.path.join(up, module_path))
    return os.path.normpath(up)


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class Bridge:
    """Bridge that can start/stop a SolidLSP language server and dispatch tool calls."""

    # File extension → language identifier mapping for per-file dispatch.
    _EXT_TO_LANGUAGE: dict[str, str] = {
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "typescript",
        ".jsx": "typescript",
        ".mts": "typescript",
        ".mjs": "typescript",
        ".cts": "typescript",
        ".cjs": "typescript",
        ".py": "python",
        ".pyi": "python",
    }

    def __init__(self) -> None:
        self.ls: SolidLanguageServer | None = None
        self.cwd: str | None = None
        self.language: str | None = None
        self._languages: list[str] = []
        self._ls_map: dict[str, SolidLanguageServer] = {}
        self.exclude_dot_paths: bool = True
        # Cache the tool contracts for validation
        self._tool_contracts: dict[str, object] | None = None

    def init(self, cwd: str) -> dict[str, object]:
        """Start language servers for every configured language in *cwd*.

        Reads ``.serenaproject.yml`` to determine which language(s) to activate.
        If absent, auto-detects the primary language and writes a default config.
        Starts a language server for **every** configured language, storing them
        in ``_ls_map`` for per-file dispatch.
        """
        project_root = str(Path(cwd).resolve())
        languages = self._read_languages(project_root)

        if not languages:
            languages = self._detect_languages(project_root)
            # Auto-write .serenaproject.yml if it was absent
            self._write_languages(project_root, languages)

        if not languages:
            raise RuntimeError(
                f"No languages configured for {project_root}. "
                "Place a .serenaproject.yml with a 'languages' list in the project root."
            )

        self._languages = list(languages)

        settings = SolidLSPSettings(
            solidlsp_dir=str(Path.home() / ".solidlsp"),
            project_data_path=str(Path(project_root) / ".solidlsp"),
        )

        # Start one language server per configured language
        self._ls_map = {}
        for lang_name in languages:
            lang = Language(lang_name)
            config = LanguageServerConfig(
                code_language=lang,
                encoding="utf-8",
            )
            ls_instance = SolidLanguageServer.create(config, project_root, solidlsp_settings=settings)
            ls_instance.start()
            self._ls_map[str(lang)] = ls_instance

        # Parse exclude_dot_paths (default True to skip dot-directories during indexing)
        self.exclude_dot_paths = self._read_exclude_dot_paths(project_root)

        # Primary (first) language server for project-wide tools
        self.language = str(Language(languages[0]))
        self.ls = self._ls_map[self.language]
        self.cwd = project_root

        return {
            "ok": True,
            "language": self.language,
            "languages": [str(Language(l)) for l in languages],
            "exclude_dot_paths": self.exclude_dot_paths,
            "cwd": project_root,
        }

    def shutdown(self) -> str:
        """Stop all language servers cleanly."""
        for ls_instance in self._ls_map.values():
            try:
                ls_instance.stop()
            except Exception:
                pass
        self._ls_map = {}
        self.ls = None
        self._languages = []
        self.cwd = None
        self.language = None
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
        elif tool_name == "get_type":
            return self._get_type(params)
        elif tool_name == "get_references":
            return self._get_references(params)
        elif tool_name == "get_implementations":
            return self._get_implementations(params)
        elif tool_name == "get_docstring":
            return self._get_docstring(params)
        elif tool_name == "rename_symbol":
            return self._rename_symbol(params)
        elif tool_name == "get_document_overview":
            return self._get_document_overview(params)
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
        """Validate required params are present and types match the contract schema."""
        schema = contract.get("params")
        if not isinstance(schema, dict):
            return
        required: list[str] = schema.get("required", []) or []  # type: ignore[assignment]
        for key in required:
            if key not in params:
                raise ValueError(
                    f"Tool '{tool_name}' requires parameter '{key}'"
                )
        try:
            jsonschema.validate(instance=params, schema=schema)
        except jsonschema.ValidationError as exc:
            raise ValueError(
                f"Invalid parameter for tool '{tool_name}': {exc.message}"
            ) from exc

    # -- find_symbol tool --------------------------------------------------

    _RG_JSON_LINE_RE = re.compile(r"^\s*\{")

    def _find_symbol(self, params: dict[str, object]) -> dict[str, object]:
        name_path_str = str(params["name_path"])
        if not name_path_str.strip():
            raise ValueError("name_path must not be empty or whitespace-only")
        relative_path = params.get("relative_path")
        if relative_path is not None:
            relative_path = str(relative_path)
        code_snippet = params.get("code_snippet")
        if code_snippet is not None:
            code_snippet = str(code_snippet)
        kinds: list[int] | None = None
        raw_kinds = params.get("kinds")
        if raw_kinds is not None and isinstance(raw_kinds, list):
            # Accept SymbolKind names (strings) and convert to integers for filtering.
            kinds = []
            for k in raw_kinds:
                if isinstance(k, str):
                    try:
                        kinds.append(SymbolKind[k].value)
                    except KeyError:
                        raise ValueError(f"Unknown SymbolKind name: {k!r}")
                else:
                    kinds.append(int(k))
        max_matches = int(params.get("max_matches", 10))

        matcher = NamePathMatcher(name_path_str)

        # 1. Determine which language servers to query
        if relative_path is not None:
            # Per-file dispatch: use the LS for this file's extension
            ls_instances = [self._ls_for_file(relative_path)]
        else:
            # Project-wide: iterate all configured language servers
            ls_instances = list(self._ls_map.values())

        # 2. Get symbol trees from all relevant LS instances
        matched: list[UnifiedSymbolInformation] = []
        for ls in ls_instances:
            tree = ls.request_full_symbol_tree(
                within_relative_path=relative_path if relative_path else None
            )
            flat_symbols = list(self._flatten_tree(tree))
            for sym in flat_symbols:
                # Apply exclude_dot_paths filtering
                if self.exclude_dot_paths:
                    loc = sym.get("location") or {}
                    rel = loc.get("relativePath")
                    if rel and _is_dot_path(str(rel)):
                        continue
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

    # -- get_type tool -----------------------------------------------------

    def _get_type(self, params: dict[str, object]) -> dict[str, object]:
        """Resolve a name_path to its defining symbol and return compact info."""
        name_path = str(params["name_path"])
        if not name_path.strip():
            raise ValueError("name_path must not be empty or whitespace-only")
        relative_path = str(params["relative_path"]) if params.get("relative_path") is not None else None

        ls_list = self._ls_list_for(relative_path)
        symbol = resolve_unique_symbol_via_workspace(
            ls_list, name_path, relative_path, exclude_dot_paths=self.exclude_dot_paths
        )

        # Get the position from selectionRange (fall back to range)
        selection_range = symbol.get("selectionRange") or symbol.get("range")
        if selection_range is None:
            raise ValueError("Symbol has no selectionRange or range.")

        start = selection_range["start"]
        line = start["line"]
        column = start["character"]

        location = symbol.get("location") or {}
        relative_file_path = location.get("relativePath")
        if not relative_file_path:
            raise ValueError("Symbol has no relativePath in location.")

        # Use the LS appropriate for the resolved symbol's file
        defining_ls = self._ls_for_file(relative_file_path)

        # Go to definition
        defining = defining_ls.request_defining_symbol(
            relative_file_path,  # type: ignore[arg-type]
            line,
            column,
        )

        if defining is None:
            raise ValueError("Could not resolve type definition.")

        # Format compact result
        defining_location = defining.get("location") or {}
        # Use selectionRange for the start (name position) and range for the
        # end (body position) so the output covers the full body span.
        defining_selection_range = defining.get("selectionRange") or {}
        defining_body_range = defining.get("range") or {}

        start_line = defining_selection_range.get("start", {}).get("line", 0) + 1
        end_line = defining_body_range.get("end", {}).get("line", 0) + 1

        result: dict[str, object] = {
            "name_path": compute_name_path(defining),
            "kind": SymbolKind(defining["kind"]).name,
            "location": (
                f"{defining_location.get('relativePath', '')}:"
                f"{start_line}-{end_line}"
            ),
        }
        return result
    # -- get_references tool -----------------------------------------------

    def _get_references(self, params: dict[str, object]) -> list[dict[str, object]]:
        """Find all references to the symbol identified by *name_path*."""
        name_path = str(params["name_path"])
        if not name_path.strip():
            raise ValueError("name_path must not be empty or whitespace-only")
        relative_path = str(params["relative_path"]) if params.get("relative_path") is not None else None

        ls_list = self._ls_list_for(relative_path)
        symbol = resolve_unique_symbol_via_workspace(
            ls_list, name_path, relative_path, exclude_dot_paths=self.exclude_dot_paths
        )
        location = symbol.get("location")
        if not location:
            raise SymbolResolutionError(name_path, f"Symbol {name_path!r} has no source location.")

        ref_relative_path = location["relativePath"]
        if ref_relative_path is None:
            raise SymbolResolutionError(name_path, f"Symbol {name_path!r} has no relative path.")

        line = location["range"]["start"]["line"]
        column = location["range"]["start"]["character"]

        # Use the LS appropriate for the resolved symbol's file
        ref_ls = self._ls_for_file(ref_relative_path)
        references = ref_ls.request_references(ref_relative_path, line, column)

        results: list[dict[str, object]] = []
        for ref in references:
            ref_rel = ref.get("relativePath")
            if ref_rel is None:
                continue
            ref_line = ref["range"]["start"]["line"]
            ref_col = ref["range"]["start"]["character"]
            ref_end_line = ref["range"]["end"]["line"]

            # Use the LS for the reference's file
            ref_file_ls = self._ls_for_file(ref_rel)
            # Try to get the symbol at the reference location for richer info
            sym = ref_file_ls._request_symbol_at_location(ref_rel, ref_line, ref_col)
            if sym is not None:
                try:
                    np = compute_name_path(sym)
                except Exception:
                    np = sym.get("name", Path(ref_rel).stem)
                kind_str = SymbolKind(sym["kind"]).name
            else:
                np = Path(ref_rel).stem
                kind_str = "Reference"

            location_str = f"{ref_rel}:{ref_line + 1}-{ref_end_line + 1}"

            results.append({
                "referrer": np,
                "kind": kind_str,
                "location": location_str,
            })

        return results

    # -- get_implementations tool -------------------------------------------

    def _get_implementations(self, params: dict[str, object]) -> dict[str, object]:
        """Resolve *name_path* to a unique symbol and return its implementing symbols."""
        name_path = str(params["name_path"])
        if not name_path.strip():
            raise ValueError("name_path must not be empty or whitespace-only")
        relative_path = str(params["relative_path"]) if params.get("relative_path") is not None else None

        ls_list = self._ls_list_for(relative_path)
        symbol = resolve_unique_symbol_via_workspace(
            ls_list, name_path, relative_path, exclude_dot_paths=self.exclude_dot_paths
        )

        location = symbol.get("location") or {}
        relative_file_path = location.get("relativePath", "")
        range_info = location.get("range", {})
        line = range_info.get("start", {}).get("line", 0)
        column = range_info.get("start", {}).get("character", 0)

        # Use the LS appropriate for the resolved symbol's file
        impl_ls = self._ls_for_file(relative_file_path) if relative_file_path else self.ls
        assert impl_ls is not None

        try:
            results = impl_ls.request_implementing_symbols(
                relative_file_path, line, column
            )
        except Exception as exc:
            # Graceful error for unimplemented LS capability
            if isinstance(exc, LSPError):
                code = getattr(exc, "code", None)
                if code == -32601:
                    return {
                        "error": "textDocument/implementation not supported by this language server."
                    }
            msg = str(exc).lower()
            if "method not found" in msg or "-32601" in msg:
                return {
                    "error": "textDocument/implementation not supported by this language server."
                }
            raise

        result_list: list[dict[str, object]] = []
        for sym in results:
            sym_loc = sym.get("location") or {}
            sym_range = sym_loc.get("range", {})
            result_list.append({
                "name_path": compute_name_path(sym),
                "kind": SymbolKind(sym["kind"]).name,
                "location": (
                    f"{sym_loc.get('relativePath', '')}:"
                    f"{sym_range.get('start', {}).get('line', 0) + 1}-"
                    f"{sym_range.get('end', {}).get('line', 0) + 1}"
                ),
            })

        return {"symbols": result_list}

    # -- get_docstring tool --------------------------------------------------

    def _get_docstring(self, params: dict[str, object]) -> str:
        """Return hover text for the symbol identified by *name_path*."""
        name_path = str(params["name_path"])
        if not name_path.strip():
            raise ValueError("name_path must not be empty or whitespace-only")
        relative_path = str(params["relative_path"]) if params.get("relative_path") is not None else None

        ls_list = self._ls_list_for(relative_path)
        symbol = resolve_unique_symbol_via_workspace(
            ls_list, name_path, relative_path, exclude_dot_paths=self.exclude_dot_paths
        )

        # Extract position from selectionRange (fall back to range).
        sel_range = symbol.get("selectionRange") or symbol.get("range")
        if sel_range is None:
            return "No docstring available."
        line = sel_range["start"]["line"]
        column = sel_range["start"]["character"]

        # Get the file path.
        location = symbol.get("location")
        if location is None:
            return "No docstring available."
        file_path = location["relativePath"]

        # Use the LS appropriate for the resolved symbol's file
        doc_ls = self._ls_for_file(file_path)
        hover = doc_ls.request_hover(file_path, line, column)
        text = self._extract_hover_text(hover)
        return text if text else "No docstring available."

    @staticmethod
    def _extract_hover_text(hover: object) -> str:
        """Extract plain text from an LSP Hover result."""
        if hover is None:
            return ""
        if not isinstance(hover, dict):
            return ""

        contents = hover.get("contents")
        if contents is None:
            return ""

        # MarkupContent (has 'kind' and 'value') or MarkedString (has 'language' and 'value').
        if isinstance(contents, dict):
            if "value" in contents:
                return str(contents["value"])
            return ""

        # Plain string.
        if isinstance(contents, str):
            return contents

        # List of MarkedString.
        if isinstance(contents, list):
            parts: list[str] = []
            for item in contents:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and "value" in item:
                    parts.append(str(item["value"]))
            return "\n".join(parts)

        return ""

    # -- rename_symbol tool --------------------------------------------------

    def _rename_symbol(self, params: dict[str, object]) -> str:
        """Rename a symbol throughout the project using direct SolidLSP."""
        name_path = str(params["name_path"])
        if not name_path.strip():
            raise ValueError("name_path must not be empty or whitespace-only")
        new_name = str(params["new_name"])
        relative_path = str(params["relative_path"]) if params.get("relative_path") is not None else None

        ls_list = self._ls_list_for(relative_path)
        try:
            symbol = resolve_unique_symbol_via_workspace(
                ls_list, name_path, relative_path, exclude_dot_paths=self.exclude_dot_paths
            )
        except SymbolResolutionError as exc:
            candidates_json = json.dumps(exc.candidates, ensure_ascii=False, default=str)
            return f"Error: {exc} Candidates: {candidates_json}"

        # Extract position: prefer selectionRange, fall back to range
        sel_range = symbol.get("selectionRange") or symbol.get("range")
        if sel_range is None:
            return f"Error: symbol {name_path!r} has no position information"
        start = sel_range.get("start")
        if start is None:
            return f"Error: symbol {name_path!r} has no start position"
        line = start.get("line")
        character = start.get("character")
        if line is None or character is None:
            return f"Error: symbol {name_path!r} has invalid position"

        # Get file path from the symbol's location
        location = symbol.get("location") or {}
        relative_file_path = location.get("relativePath")
        if not relative_file_path or not isinstance(relative_file_path, str):
            return f"Error: symbol {name_path!r} has no relative file path"

        # Use the LS appropriate for the resolved symbol's file
        rename_ls = self._ls_for_file(relative_file_path)

        # Request the workspace edit from the LSP
        workspace_edit = rename_ls.request_rename_symbol_edit(
            relative_file_path, int(line), int(character), new_name
        )

        if workspace_edit is None:
            return "Error: rename not supported by this language server"

        # Apply the workspace edit to each changed file
        changes = workspace_edit.get("changes") or {}
        for uri, edits in changes.items():
            # Convert URI to absolute path, then to relative path
            try:
                abs_path = PathUtils.uri_to_path(uri)
            except Exception:
                # Fallback: parse the URI manually
                parsed = urllib.parse.urlparse(uri)
                abs_path = urllib.parse.unquote(parsed.path)
            try:
                target_relative = os.path.relpath(abs_path, rename_ls.repository_root_path)
            except ValueError:
                target_relative = abs_path

            # Determine which LS handles this file
            file_ls = self._ls_for_file(target_relative)

            # Open the file buffer, apply edits, then persist to disk
            with file_ls.open_file(target_relative) as file_buffer:
                file_ls.apply_text_edits_to_file(target_relative, edits)
                abs_file_path = Path(file_ls.repository_root_path) / target_relative
                abs_file_path.write_text(file_buffer.contents, encoding="utf-8")

        return f"renamed {name_path} to {new_name}"

    # -- get_document_overview tool -----------------------------------------

    def _get_document_overview(self, params: dict[str, object]) -> str:
        """Return a two-section plain-text overview of a source file.

        Section 1 — "## Imports": source modules with imported names,
        classified as [internal] (project-local, resolved to definition
        location) or [external] (stdlib/package).

        Section 2 — "## Symbols": locally-defined symbols with
        ``Kind Name:startLine-endLine`` and 2-space indentation,
        filtered to exclude imported bindings.

        Dispatches to the correct language server based on file extension.
        """
        relative_path = str(params["relative_path"])
        depth = int(params.get("depth", 0))

        assert self.cwd is not None

        # Read the source file
        abs_path = Path(self.cwd) / relative_path
        if not abs_path.is_file():
            raise FileNotFoundError(f"File not found: {relative_path}")
        source = abs_path.read_text(encoding="utf-8")

        # Detect language from file extension for per-file dispatch
        file_language = self._language_for_file(relative_path)
        ls = self._ls_for_file(relative_path)

        # Parse imports via tree-sitter (returns empty list for unsupported languages)
        import_pairs = parse_imports(source, file_language)  # [(original, binding, module)]

        # Build output sections
        sections: list[str] = []

        if import_pairs:
            imports_section = self._format_imports_section(import_pairs, relative_path, ls)
            sections.append("## Imports")
            sections.append(imports_section)

        # Get document symbols and filter out imported names
        doc_symbols = ls.request_document_symbols(relative_path)
        imported_names: set[str] = {binding for _, binding, _ in import_pairs}
        filtered_root_symbols = self._filter_imported_symbols(
            doc_symbols.root_symbols, imported_names
        )

        # Format symbols with line ranges and depth
        symbols_text = self._format_overview_symbols(filtered_root_symbols, depth, 0)
        sections.append("## Symbols")
        sections.append(symbols_text)

        return "\n".join(sections)

    def _format_imports_section(
        self,
        import_pairs: list[tuple[str, str, str]],
        file_relative_path: str,
        ls: SolidLanguageServer,
    ) -> str:
        """Group imports by source module and produce one line per module.

        Displays ``original (as binding)`` only when the two names differ.
        Resolves via *original_name* (the workspace-known symbol).
        """
        by_module: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for original, binding, module in import_pairs:
            by_module[module].append((original, binding))

        lines: list[str] = []
        for module, name_pairs in sorted(by_module.items()):
            display_names: list[str] = []
            for original, binding in name_pairs:
                if original == binding:
                    display_names.append(original)
                else:
                    display_names.append(f"{original} (as {binding})")
            names_str = ", ".join(display_names)
            # Use original names for workspace resolution
            original_names = [orig for orig, _ in name_pairs]
            classification = self._classify_import(module, original_names, file_relative_path, ls)
            lines.append(f"{module} — {names_str} {classification}")

        return "\n".join(lines)

    def _classify_import(
        self,
        module: str,
        names: list[str],
        file_relative_path: str,
        ls: SolidLanguageServer,
    ) -> str:
        """Classify a source module as internal or external.

        Relative module paths (starting with ``.``) are always internal.
        Non-relative modules are resolved via workspace symbol search:
        internal if at least one imported name resolves, external otherwise.
        """
        # Relative import — definitely internal
        if module.startswith("."):
            location = self._resolve_import_location(names, file_relative_path, module, ls)
            if location:
                return f"[internal → {location}]"
            return "[internal]"

        # Non-relative — try to resolve names
        location = self._resolve_import_location(names, file_relative_path, module, ls)
        if location:
            return f"[internal → {location}]"
        return "[external]"

    def _resolve_import_location(
        self,
        names: list[str],
        file_relative_path: str,
        module: str,
        ls: SolidLanguageServer,
    ) -> str | None:
        """Try to resolve imported names to a definition location.

        Returns ``"rel/path:start-end"`` on first successful resolution,
        or ``None`` if all names fail to resolve.

        For relative module specifiers (starting with ``.``), the search
        scope is computed by resolving *module* against the file's parent
        directory, so cross-directory imports (e.g. ``../src/foo``) scope
        correctly.  For non-relative specifiers the scope stays the file's
        own directory (existing behaviour).
        """
        # Compute the search scope based on the module specifier
        raw_dir = os.path.dirname(file_relative_path)  # empty string for root files
        if module.startswith("."):
            # Relative import — resolve against the file's parent directory.
            # Two styles:
            #   TS  — "../src/foo"  (slashes, os.path handles natively)
            #   Py  — "..src.utils"  (dots as module separator)
            base_dir = raw_dir or "."
            if "/" in module:
                # TypeScript-style: slashes act as path separators
                resolved = os.path.normpath(os.path.join(base_dir, module))
            else:
                # Python-style: leading dots = depth, rest uses "." as separator
                resolved = _resolve_python_module(base_dir, module)
            scope_dir = os.path.dirname(resolved) or None
        else:
            # Non-relative import — scope to the file's own directory,
            # or None (project-wide) when file is in the project root.
            scope_dir = raw_dir or None

        for name in names:
            try:
                symbol = resolve_unique_symbol_via_workspace(
                    [ls], name, relative_path=scope_dir
                )
            except Exception:
                continue

            location = symbol.get("location") or {}
            rel_path = location.get("relativePath")
            rng = location.get("range") or {}
            start = rng.get("start", {}).get("line", 0) + 1
            end = rng.get("end", {}).get("line", 0) + 1

            if rel_path:
                return f"{rel_path}:{start}-{end}"

        return None

    @staticmethod
    def _filter_imported_symbols(
        symbols: list[UnifiedSymbolInformation],
        imported_names: set[str],
    ) -> list[UnifiedSymbolInformation]:
        """Recursively filter symbols whose names appear in *imported_names*.

        Returns a new list — does not mutate the input.
        """
        result: list[UnifiedSymbolInformation] = []
        for sym in symbols:
            if sym.get("name") in imported_names:
                continue
            # Copy to avoid mutating the original (only need top-level keys)
            filtered: dict = {}
            for k, v in sym.items():
                if k == "children" and v:
                    filtered[k] = Bridge._filter_imported_symbols(v, imported_names)
                else:
                    filtered[k] = v
            result.append(filtered)  # type: ignore[arg-type]
        return result

    def _start_language_lazily(self, language: str) -> SolidLanguageServer:
        """Start a language server for *language* on demand.

        Validates the language is known to SolidLSP, creates and starts a
        server, appends the language to ``.serenaproject.yml``, and returns
        the new server instance.

        Does not mutate ``.serenaproject.yml`` if the language server fails
        to start.
        """
        assert self.cwd is not None

        print(
            f"[pi-serena-lsp] lazily starting {language} language server...",
            file=sys.stderr,
        )

        # 1. Validate that SolidLSP knows this language.
        try:
            lang = Language(language)
        except ValueError as exc:
            raise ValueError(
                f"Language {language!r} is not supported by SolidLSP. "
                f"Known languages: {sorted(l.value for l in Language)}"
            ) from exc

        lang_str = str(lang)

        # 2. Create and start the language server.
        config = LanguageServerConfig(code_language=lang, encoding="utf-8")

        settings = SolidLSPSettings(
            solidlsp_dir=str(Path.home() / ".solidlsp"),
            project_data_path=str(Path(self.cwd) / ".solidlsp"),
        )

        ls_instance = SolidLanguageServer.create(
            config, self.cwd, solidlsp_settings=settings
        )
        ls_instance.start()

        # 3. Store in the server map.
        self._ls_map[lang_str] = ls_instance

        # 4. Append to .serenaproject.yml so next init starts it eagerly.
        self._append_language_to_config(lang_str)
        if lang_str not in self._languages:
            self._languages.append(lang_str)

        return ls_instance

    def _append_language_to_config(self, language: str) -> None:
        """Append *language* to the languages list in ``.serenaproject.yml``.

        Creates the file if it doesn't exist.  No-op if *language* is already
        listed.
        """
        assert self.cwd is not None
        config_path = Path(self.cwd) / ".serenaproject.yml"

        if config_path.is_file():
            with open(config_path, encoding="utf-8") as f:
                cfg: object = yaml.safe_load(f)
            if not isinstance(cfg, dict):
                cfg = {}
            languages: list[str] = list(cfg.get("languages", []) or [])
        else:
            cfg = {}
            languages = []

        if language in languages:
            return

        languages.append(language)
        cfg["languages"] = languages

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, default_flow_style=False)

    @staticmethod
    def _format_overview_symbols(
        symbols: list[UnifiedSymbolInformation],
        max_depth: int,
        current_depth: int,
    ) -> str:
        """Format symbols as ``Kind Name:startLine-endLine`` with 2-space indent."""
        lines: list[str] = []
        indent = "  " * current_depth
        for sym in symbols:
            kind_name = SymbolKind(sym["kind"]).name
            name = sym["name"]

            # Get the symbol's body line range (use "range", not "selectionRange")
            rng = sym.get("range") or {}
            start_line = rng.get("start", {}).get("line", 0) + 1
            end_line = rng.get("end", {}).get("line", 0) + 1

            lines.append(f"{indent}{kind_name} {name}:{start_line}-{end_line}")

            if current_depth < max_depth:
                children = sym.get("children", [])
                if children:
                    lines.append(
                        Bridge._format_overview_symbols(
                            children, max_depth, current_depth + 1
                        )
                    )
        return "\n".join(lines)

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
        start_line = rng["start"]["line"] + 1
        end_line = rng["end"]["line"] + 1
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
        # Scope path — default to cwd to avoid runaway searches
        if within_path is not None:
            cmd.append(within_path)
        else:
            cmd.append(".")

        try:
            proc = subprocess.run(
                cmd,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=10,
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
                if sym_start <= occ_end and sym_end >= occ_start:
                    result.append(sym)
                    break

        return result

    @staticmethod
    def _read_exclude_dot_paths(project_root: str) -> bool:
        """Read ``exclude_dot_paths`` from ``.serenaproject.yml``.  Defaults to ``True``."""
        config_path = Path(project_root) / ".serenaproject.yml"
        if not config_path.is_file():
            return True
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg: object = yaml.safe_load(f)
        except yaml.YAMLError:
            return True
        if not isinstance(cfg, dict):
            return True
        return bool(cfg.get("exclude_dot_paths", True))

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

    @staticmethod
    def _write_languages(project_root: str, languages: list[str]) -> None:
        """Write a default ``.serenaproject.yml`` if none exists."""
        config_path = Path(project_root) / ".serenaproject.yml"
        if config_path.is_file():
            return  # already exists
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump({"languages": languages}, f, default_flow_style=False)

    def _language_for_file(self, relative_path: str) -> str:
        """Return the language identifier for *relative_path* based on extension.

        Falls back to the primary language if the extension is unrecognised.
        """
        suffix = Path(relative_path).suffix.lower()
        if suffix in self._EXT_TO_LANGUAGE:
            return self._EXT_TO_LANGUAGE[suffix]
        return self.language or ""

    def _ls_list_for(self, relative_path: str | None) -> list[SolidLanguageServer]:
        """Return the appropriate LS instances to search.

        When *relative_path* is given (scoped to a file or directory), returns
        a single-element list with the LS for that file's language.  When
        omitted (project-wide search), returns all configured LS instances.
        """
        if relative_path is not None:
            return [self._ls_for_file(relative_path)]
        return list(self._ls_map.values())

    def _ls_for_file(self, relative_path: str) -> SolidLanguageServer:
        """Return the language server instance appropriate for *relative_path*.

        If the language is not yet started, tries to start it lazily.
        Falls back to the primary server only when the file extension is
        unrecognised (language matches the primary).
        """
        language = self._language_for_file(relative_path)
        if language in self._ls_map:
            return self._ls_map[language]
        # Unrecognised extension → falls back to primary (existing behaviour)
        if language == self.language:
            assert self.ls is not None
            return self.ls
        # Recognised extension but no running server → start lazily
        return self._start_language_lazily(language)


# ---------------------------------------------------------------------------
# JSONL protocol helpers
# ---------------------------------------------------------------------------


def respond(
    request_id: object,
    ok: bool,
    result: object = None,
    error: str | None = None,
    error_data: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {"id": request_id, "ok": ok}
    if ok:
        payload["result"] = result
    else:
        error_payload: dict[str, object] = {
            "kind": "error",
            "message": error or "Unknown error",
        }
        if error_data:
            error_payload.update(error_data)
        payload["error"] = error_payload
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
                params = request.get("params", {})
                if not isinstance(params, dict):
                    raise ValueError("params must be a JSON object")
                result = bridge.call_tool(tool_name, params)
            else:
                raise ValueError(f"Unknown method: {method}")

            respond(request_id, True, result)
        except SymbolResolutionError as exc:
            traceback.print_exc(file=sys.stderr)
            try:
                respond(
                    request_id,
                    False,
                    error=str(exc),
                    error_data={
                        "kind": "ambiguity",
                        "candidates": exc.candidates,
                    },
                )
            except Exception:
                pass  # broken pipe — process will exit anyway
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
