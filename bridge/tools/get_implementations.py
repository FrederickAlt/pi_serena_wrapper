"""``get_implementations`` tool — find implementing symbols for an interface."""

from __future__ import annotations

import formatting
from solidlsp.ls_types import SymbolKind
from solidlsp.lsp_protocol_handler.server import LSPError
from name_path import compute_name_path
from tool_context import ToolContext
from resolution import resolve_tool_symbol


def get_implementations(params: dict[str, object], ctx: ToolContext) -> dict[str, object]:
    """Resolve ``name_path`` and return implementing symbols."""
    resolved = resolve_tool_symbol(params, ctx)

    try:
        results = resolved.ls.request_implementing_symbols(
            resolved.file_path, resolved.line, resolved.column
        )
    except Exception as exc:
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
            "location": formatting.format_location_str(
                str(sym_loc.get("relativePath", "")),
                sym_range.get("start", {}).get("line", 0) + 1,
                sym_range.get("end", {}).get("line", 0) + 1,
            ),
        })

    return {"symbols": result_list}
