"""``get_type`` tool — resolve a name_path to its defining type symbol."""

from __future__ import annotations

import formatting
from solidlsp.ls_types import SymbolKind
from name_path import compute_name_path
from tool_context import ToolContext
from resolution import resolve_tool_symbol


def get_type(params: dict[str, object], ctx: ToolContext) -> dict[str, object]:
    """Resolve a name_path to its defining symbol and return compact info."""
    resolved = resolve_tool_symbol(params, ctx)

    defining = resolved.ls.request_defining_symbol(
        resolved.file_path, resolved.line, resolved.column,
    )

    if defining is None:
        raise ValueError("Could not resolve type definition.")

    defining_location = defining.get("location") or {}
    defining_selection_range = defining.get("selectionRange") or {}
    defining_body_range = defining.get("range") or {}

    start_line = defining_selection_range.get("start", {}).get("line", 0) + 1
    end_line = defining_body_range.get("end", {}).get("line", 0) + 1

    return {
        "name_path": compute_name_path(defining),
        "kind": SymbolKind(defining["kind"]).name,
        "location": formatting.format_location_str(
            str(defining_location.get("relativePath", "")), start_line, end_line
        ),
    }
