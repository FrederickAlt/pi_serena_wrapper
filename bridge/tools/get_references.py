"""``get_references`` tool — find all usages of a symbol."""

from __future__ import annotations

from pathlib import Path

from solidlsp.ls_types import SymbolKind
from name_path import compute_name_path
from tool_context import ToolContext
from resolution import resolve_tool_symbol


def get_references(params: dict[str, object], ctx: ToolContext) -> list[dict[str, object]]:
    """Find all references to the symbol identified by ``name_path``."""
    resolved = resolve_tool_symbol(params, ctx)

    references = resolved.ls.request_references(resolved.file_path, resolved.line, resolved.column)

    results: list[dict[str, object]] = []
    for ref in references:
        ref_rel = ref.get("relativePath")
        if ref_rel is None:
            continue
        ref_line = ref["range"]["start"]["line"]
        ref_col = ref["range"]["start"]["character"]
        ref_end_line = ref["range"]["end"]["line"]

        ref_file_ls = ctx.ls_for_file(ref_rel)  # type: ignore[call-arg]
        sym = ref_file_ls.request_symbol_at_location(ref_rel, ref_line, ref_col)
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
