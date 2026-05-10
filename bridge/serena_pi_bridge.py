#!/usr/bin/env python3
"""Minimal JSONL bridge that starts SolidLSP for a given project.

This is the bootstrap bridge for Issue #1 — it handles init/shutdown lifecycle
only.  Tool dispatch will be added in follow-up issues.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
import urllib.parse
from pathlib import Path

# Ensure the vendored solidlsp (sibling directory) is importable.
_BRIDGE_DIR = Path(__file__).resolve().parent
if str(_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_DIR))

import yaml

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.ls_utils import PathUtils
from solidlsp.settings import SolidLSPSettings

from name_path import resolve_unique_symbol, SymbolResolutionError

PACKAGE_ROOT = _BRIDGE_DIR.parent
SERENA_HOME = PACKAGE_ROOT / ".serena-data"

os.environ.setdefault("SERENA_HOME", str(SERENA_HOME))


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class Bridge:
    """Minimal bridge that can start and stop a SolidLSP language server."""

    def __init__(self) -> None:
        self.ls: SolidLanguageServer | None = None
        self.cwd: str | None = None

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

    def call_tool(self, tool: str, args: dict[str, object]) -> object:
        """Dispatch a tool call to the appropriate handler."""
        if self.ls is None:
            raise RuntimeError("Bridge has not been initialized. Call init first.")

        if tool == "rename_symbol":
            return self.rename_symbol(**args)  # type: ignore[arg-type]
        else:
            raise ValueError(f"Unknown tool: {tool}")

    # -- tools -------------------------------------------------------------

    def rename_symbol(
        self,
        name_path: str,
        new_name: str,
        relative_path: str | None = None,
    ) -> str:
        """Rename a symbol throughout the project using direct SolidLSP.

        Uses ``resolve_unique_symbol`` to find the symbol, then calls
        ``request_rename_symbol_edit`` to compute the workspace edit.
        Applies the edit to all affected files.
        """
        if self.ls is None:
            raise RuntimeError("Bridge has not been initialized. Call init first.")

        try:
            symbol = resolve_unique_symbol(self.ls, name_path, relative_path)
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
        line = start.get("line")  # type: ignore[assignment]
        character = start.get("character")  # type: ignore[assignment]
        if line is None or character is None:
            return f"Error: symbol {name_path!r} has invalid position"

        # Get file path from the symbol's location
        location = symbol.get("location") or {}
        relative_file_path = location.get("relativePath")
        if not relative_file_path or not isinstance(relative_file_path, str):
            return f"Error: symbol {name_path!r} has no relative file path"

        # Request the workspace edit from the LSP
        workspace_edit = self.ls.request_rename_symbol_edit(
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
                target_relative = os.path.relpath(abs_path, self.ls.repository_root_path)
            except ValueError:
                # On Windows, paths might be on different drives
                target_relative = abs_path

            # Open the file buffer, apply edits, then persist to disk
            with self.ls.open_file(target_relative) as file_buffer:
                # apply_text_edits_to_file opens the file again internally,
                # but that just bumps the refcount. The buffer will still be
                # alive when we read its contents below.
                self.ls.apply_text_edits_to_file(target_relative, edits)
                # Now read the modified contents and write to disk
                abs_file_path = Path(self.ls.repository_root_path) / target_relative
                abs_file_path.write_text(file_buffer.contents, encoding="utf-8")

        return f"renamed {name_path} to {new_name}"

    # -- helpers ------------------------------------------------------------

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
                result = bridge.call_tool(str(request["tool"]), dict(request.get("args") or {}))
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
