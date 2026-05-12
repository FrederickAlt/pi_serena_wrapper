#!/usr/bin/env python3
"""JSONL bridge that starts SolidLSP for a project and dispatches tool calls.

The Bridge is now a thin facade:

* ``ProjectConfig`` owns ``.serenaproject.yml`` reading/writing.
* ``LanguageServerManager`` owns language-server lifecycle and per-file dispatch.
* ``ToolDispatcher`` owns contract validation and tool registry lookup.

The JSONL protocol stays here because this file is the subprocess entry point.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

# Ensure the vendored solidlsp (sibling directory) is importable.
_BRIDGE_DIR = Path(__file__).resolve().parent
if str(_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_DIR))

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import Language
from solidlsp.ls_types import SymbolKind

from language_server_manager import LanguageServerManager
from name_path import SymbolResolutionError
from project_config import (
    DEFAULT_DOCUMENT_OVERVIEW_KINDS as PROJECT_DEFAULT_DOCUMENT_OVERVIEW_KINDS,
    ProjectConfig,
    detect_languages,
    read_project_config,
    write_default_config,
)
from tool_context import ToolContext
from tool_dispatcher import ToolDispatcher


# Backwards-compatible export for tests/docs that referenced this constant.
DEFAULT_DOCUMENT_OVERVIEW_KINDS = PROJECT_DEFAULT_DOCUMENT_OVERVIEW_KINDS


class Bridge:
    """Facade that wires config, language servers, and tool dispatch together."""

    def __init__(self) -> None:
        self._language_servers = LanguageServerManager()
        self._tool_dispatcher = ToolDispatcher()
        self._tool_ctx: ToolContext | None = None

        # Compatibility/readability mirrors of LanguageServerManager state.
        self.ls: SolidLanguageServer | None = None
        self.cwd: str | None = None
        self.language: str | None = None
        self._languages: list[str] = []
        self._ls_map: dict[str, SolidLanguageServer] = {}
        self.exclude_dot_paths: bool = True
        self._overview_kinds: frozenset[int] = PROJECT_DEFAULT_DOCUMENT_OVERVIEW_KINDS

    def init(self, cwd: str) -> dict[str, object]:
        """Start language servers for configured or detected languages."""
        project_root = str(Path(cwd).resolve())
        config = read_project_config(project_root)

        if not config.languages:
            detected = detect_languages(project_root)
            write_default_config(project_root, detected)
            config = ProjectConfig(
                languages=detected,
                document_overview_default_kinds=config.document_overview_default_kinds,
                exclude_dot_paths=config.exclude_dot_paths,
            )

        if not config.languages:
            raise RuntimeError(
                f"No languages configured for {project_root}. "
                "Place a .serenaproject.yml with a 'languages' list in the project root."
            )

        self._language_servers.start(project_root, config.languages)
        self.exclude_dot_paths = config.exclude_dot_paths
        self._overview_kinds = config.document_overview_default_kinds
        self._sync_language_server_state()

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
            "languages": [str(Language(l)) for l in config.languages],
            "exclude_dot_paths": self.exclude_dot_paths,
            "document_overview_default_kinds": sorted(
                SymbolKind(k).name for k in sorted(self._overview_kinds)
            ),
            "cwd": project_root,
        }

    def shutdown(self) -> str:
        """Stop all language servers cleanly."""
        self._language_servers.shutdown()
        self._tool_ctx = None
        self._sync_language_server_state()
        return "OK"

    def call_tool(self, tool_name: str, params: dict[str, object]) -> object:
        """Validate and dispatch a tool call."""
        if self.ls is None or self._tool_ctx is None:
            raise RuntimeError("Bridge not initialized. Call init first.")
        return self._tool_dispatcher.call_tool(tool_name, params, self._tool_ctx)

    # -- language-server delegates -----------------------------------------

    def _language_for_file(self, relative_path: str) -> str:
        return self._language_servers.language_for_file(relative_path)

    def _ls_list_for(self, relative_path: str | None) -> list[SolidLanguageServer]:
        return self._language_servers.ls_list_for(relative_path)

    def _ls_for_file(self, relative_path: str) -> SolidLanguageServer:
        result = self._language_servers.ls_for_file(relative_path)
        self._sync_language_server_state()
        return result

    def _start_language_lazily(self, language: str) -> SolidLanguageServer:
        result = self._language_servers.start_language_lazily(language)
        self._sync_language_server_state()
        return result

    def _sync_language_server_state(self) -> None:
        """Mirror manager state onto Bridge attributes kept for compatibility."""
        self.ls = self._language_servers.ls
        self.cwd = self._language_servers.cwd
        self.language = self._language_servers.language
        self._languages = self._language_servers.languages
        self._ls_map = self._language_servers.ls_map


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
