"""Symbol resolution helper for tool implementations.

Every action tool (get_type, get_references, get_implementations,
get_docstring, rename_symbol) repeats the same ~15 lines of boilerplate
to parse params, resolve a name_path via workspace, and extract position
information.

``resolve_tool_symbol`` captures that pattern once.
"""

from __future__ import annotations

from dataclasses import dataclass

from solidlsp import SolidLanguageServer
from solidlsp.ls_types import UnifiedSymbolInformation

from name_path import resolve_unique_symbol_via_workspace
from tool_context import ToolContext


@dataclass
class ResolvedSymbol:
    """Everything a tool needs after resolving a ``name_path``."""
    symbol: UnifiedSymbolInformation
    file_path: str
    line: int
    column: int
    ls: SolidLanguageServer
    raw_params: dict[str, object]


def resolve_tool_symbol(
    params: dict[str, object],
    ctx: ToolContext,
) -> ResolvedSymbol:
    """Parse *params*, resolve ``name_path`` via workspace, extract position.

    This is the shared preamble for all action tools.  Call it once at the
    top of a tool implementation and use the returned ``ResolvedSymbol``.

    Raises ``ValueError`` on missing/invalid params, or
    ``SymbolResolutionError`` on ambiguity/no match.
    """
    name_path_str = str(params["name_path"])
    if not name_path_str.strip():
        raise ValueError("name_path must not be empty or whitespace-only")

    relative_path = str(params["relative_path"]) if params.get("relative_path") is not None else None

    ls_list = ctx.ls_list_for(relative_path)
    symbol = resolve_unique_symbol_via_workspace(
        ls_list, name_path_str, relative_path,
        exclude_dot_paths=ctx.exclude_dot_paths,
    )

    # Extract position: prefer selectionRange, fall back to range.
    sel_range = symbol.get("selectionRange") or symbol.get("range")
    if sel_range is None:
        raise ValueError(f"Symbol {name_path_str!r} has no position information.")
    start = sel_range["start"]
    line = start["line"]
    column = start["character"]

    location = symbol.get("location") or {}
    file_path = location.get("relativePath")
    if not file_path:
        raise ValueError(f"Symbol {name_path_str!r} has no relativePath in location.")

    ls_instance = ctx.ls_for_file(file_path)

    return ResolvedSymbol(
        symbol=symbol,
        file_path=file_path,
        line=line,
        column=column,
        ls=ls_instance,
        raw_params=params,
    )
