#!/usr/bin/env python3
"""JSONL bridge that starts SolidLSP and dispatches tool calls."""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

# Ensure the vendored solidlsp (sibling directory) is importable.
_BRIDGE_DIR = Path(__file__).resolve().parent
if str(_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_DIR))

import yaml

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.ls_types import SymbolKind
from solidlsp.lsp_protocol_handler.server import LSPError
from solidlsp.settings import SolidLSPSettings

from name_path import (
    SymbolResolutionError,
    compute_name_path,
    resolve_unique_symbol,
)

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

    # -- tools ---------------------------------------------------------------

    def get_implementations(
        self, name_path: str, relative_path: str | None = None
    ) -> dict[str, object]:
        """Resolve *name_path* to a unique symbol and return its implementing symbols."""
        if self.ls is None:
            raise RuntimeError("Language server not initialized")

        try:
            symbol = resolve_unique_symbol(self.ls, name_path, relative_path)
        except SymbolResolutionError:
            raise  # re-raise — handled by the caller

        location = symbol.get("location") or {}
        relative_file_path = location.get("relativePath", "")
        range_info = location.get("range", {})
        line = range_info.get("start", {}).get("line", 0)
        column = range_info.get("start", {}).get("character", 0)

        try:
            results = self.ls.request_implementing_symbols(
                relative_file_path, line, column
            )
        except Exception as exc:
            # Check for unimplemented LS capability (MethodNotFound from LSP).
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
                    f"{sym_range.get('start', {}).get('line', 0)}-"
                    f"{sym_range.get('end', {}).get('line', 0)}"
                ),
            })

        return {"symbols": result_list}

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
    error: str | dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {"id": request_id, "ok": ok}
    if ok:
        payload["result"] = result
    else:
        if isinstance(error, dict):
            payload["error"] = error
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
            elif method == "get_implementations":
                name_path = str(request["name_path"])
                relative_path = request.get("relative_path")
                result = bridge.get_implementations(
                    name_path,
                    str(relative_path) if relative_path else None,
                )
            else:
                raise ValueError(f"Unknown method: {method}")

            respond(request_id, True, result)
        except SymbolResolutionError as sre:
            traceback.print_exc(file=sys.stderr)
            try:
                error_payload: dict[str, object] = {
                    "kind": "symbol_resolution_error",
                    "message": str(sre),
                }
                if sre.candidates:
                    error_payload["candidates"] = sre.candidates
                respond(
                    request_id,
                    False,
                    error=error_payload,
                )
            except Exception:
                pass
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
