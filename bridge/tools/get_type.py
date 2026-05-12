"""``get_type`` tool — resolve a name_path to its defining type symbol."""

from __future__ import annotations

import formatting
from solidlsp.ls_types import SymbolKind, UnifiedSymbolInformation
from name_path import compute_name_path
from tool_context import ToolContext
from resolution import resolve_tool_symbol

#: Symbol kinds that are inherently definitions (the symbol *is* the type,
#: so there is no need for an extra LSP round-trip to find its defining
#: symbol).  Skipping ``request_defining_symbol`` saves ~2 s of LSP cold
#: latency on the first call.
_SELF_DEFINING_KINDS: frozenset[int] = frozenset({
    SymbolKind.Class,
    SymbolKind.Method,
    SymbolKind.Constructor,
    SymbolKind.Enum,
    SymbolKind.Interface,
    SymbolKind.Function,
    SymbolKind.Constant,
    SymbolKind.EnumMember,
    SymbolKind.Struct,
    SymbolKind.Event,
    SymbolKind.TypeParameter,
})


def _build_result(symbol: UnifiedSymbolInformation) -> dict[str, object]:
    """Build the compact result dict from a *symbol*."""
    location = symbol.get("location") or {}
    selection_range = symbol.get("selectionRange") or {}
    body_range = symbol.get("range") or {}

    start_line = selection_range.get("start", {}).get("line", 0) + 1
    end_line = body_range.get("end", {}).get("line", 0) + 1

    return {
        "name_path": compute_name_path(symbol),
        "kind": SymbolKind(symbol["kind"]).name,
        "location": formatting.format_location_str(
            str(location.get("relativePath", "")), start_line, end_line
        ),
    }


def get_type(params: dict[str, object], ctx: ToolContext) -> dict[str, object]:
    """Resolve a name_path to its defining symbol and return compact info."""
    resolved = resolve_tool_symbol(params, ctx)

    # For self-defining symbols (Class, Function, Method, etc.), the
    # resolved symbol already carries the answer — skip the expensive
    # request_defining_symbol LSP round-trip.
    if resolved.symbol["kind"] in _SELF_DEFINING_KINDS:
        return _build_result(resolved.symbol)

    defining = resolved.ls.request_defining_symbol(
        resolved.file_path, resolved.line, resolved.column,
    )

    if defining is None:
        raise ValueError("Could not resolve type definition.")

    return _build_result(defining)
