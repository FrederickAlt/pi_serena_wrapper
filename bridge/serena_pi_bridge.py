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

import formatting

import snippet_filter

import import_resolver

from tools import TOOL_REGISTRY  # type: ignore[import-untyped]

from tool_context import ToolContext
from resolution import resolve_tool_symbol, ResolvedSymbol

PACKAGE_ROOT = _BRIDGE_DIR.parent

# ---------------------------------------------------------------------------
# Default kind filter for get_document_overview — structural kinds only.
# See ADR comment in the method docstring for reasoning.
# ---------------------------------------------------------------------------

DEFAULT_DOCUMENT_OVERVIEW_KINDS: frozenset[int] = frozenset({
    SymbolKind.Module,        # 2
    SymbolKind.Namespace,     # 3
    SymbolKind.Class,         # 5
    SymbolKind.Method,        # 6
    SymbolKind.Constructor,   # 9
    SymbolKind.Enum,          # 10
    SymbolKind.Interface,     # 11
    SymbolKind.Function,      # 12
    SymbolKind.Constant,      # 14
    SymbolKind.EnumMember,    # 22
    SymbolKind.Struct,        # 23
    SymbolKind.Event,         # 24
    SymbolKind.TypeParameter, # 26
})


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
        self._overview_kinds: frozenset[int] = DEFAULT_DOCUMENT_OVERVIEW_KINDS
        # Cache the tool contracts for validation
        self._tool_contracts: dict[str, object] | None = None
        # Lazily-built tool context (rebuilt whenever init changes state)
        self._tool_ctx: ToolContext | None = None

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

        # Parse document_overview_default_kinds from config (or use hardcoded default)
        self._overview_kinds = self._read_document_overview_kinds(project_root)

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

        # Build ToolContext for tool dispatch
        self._tool_ctx = ToolContext(
            cwd=project_root,
            exclude_dot_paths=self.exclude_dot_paths,
            overview_kinds=self._overview_kinds,
            ls_list_for=self._ls_list_for,
            ls_for_file=self._ls_for_file,
            language_for_file=self._language_for_file,
        )

        return {
            "ok": True,
            "language": self.language,
            "languages": [str(Language(l)) for l in languages],
            "exclude_dot_paths": self.exclude_dot_paths,
            "document_overview_default_kinds": sorted(
                SymbolKind(k).name for k in sorted(self._overview_kinds)
            ),
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

        tool_fn = TOOL_REGISTRY.get(tool_name)
        if tool_fn is None:
            raise ValueError(f"Tool not implemented: {tool_name}")
        return tool_fn(params, self._tool_ctx)

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

        # 4. Track the language in memory (no config mutation — queries are read-only).
        if lang_str not in self._languages:
            self._languages.append(lang_str)

        return ls_instance



    # -- helpers ------------------------------------------------------------



    @staticmethod
    def _read_document_overview_kinds(project_root: str) -> frozenset[int]:
        """Read ``document_overview_default_kinds`` from ``.serenaproject.yml``.

        Returns the hardcoded ``DEFAULT_DOCUMENT_OVERVIEW_KINDS`` if the key
        is absent or the config file does not exist.
        """
        config_path = Path(project_root) / ".serenaproject.yml"
        if not config_path.is_file():
            return DEFAULT_DOCUMENT_OVERVIEW_KINDS
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg: object = yaml.safe_load(f)
        except yaml.YAMLError:
            return DEFAULT_DOCUMENT_OVERVIEW_KINDS
        if not isinstance(cfg, dict):
            return DEFAULT_DOCUMENT_OVERVIEW_KINDS
        raw: list[str] | None = cfg.get("document_overview_default_kinds")
        if not raw or not isinstance(raw, list):
            return DEFAULT_DOCUMENT_OVERVIEW_KINDS
        # Validate and convert
        result: set[int] = set()
        for name in raw:
            if not isinstance(name, str):
                continue
            try:
                result.add(SymbolKind[name].value)
            except KeyError:
                raise ValueError(
                    f"Unknown SymbolKind name in .serenaproject.yml "
                    f"document_overview_default_kinds: {name!r}"
                ) from None
        return frozenset(result) if result else DEFAULT_DOCUMENT_OVERVIEW_KINDS

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
        default_kind_names = sorted(
            SymbolKind(k).name for k in sorted(DEFAULT_DOCUMENT_OVERVIEW_KINDS)
        )
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                {
                    "languages": languages,
                    "document_overview_default_kinds": default_kind_names,
                },
                f,
                default_flow_style=False,
            )

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

        When *relative_path* is a file, returns a single-element list with
        the LS for that file's language.  When *relative_path* is a directory
        or omitted (project-wide search), returns all configured LS instances
        so that symbols from every language in the scope are visible.
        """
        if relative_path is not None:
            # If relative_path points to a directory on disk, we cannot
            # determine which language(s) apply → return all LS instances.
            if self.cwd is not None:
                abs_path = Path(self.cwd) / relative_path
                if abs_path.is_dir():
                    return list(self._ls_map.values())
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
