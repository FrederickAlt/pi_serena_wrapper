"""Formatting helpers extracted from the Bridge.

Pure functions for rendering symbols to strings — no Bridge state, no LSP
calls.  Callers (tool modules and the Bridge itself) import these directly.
"""

from __future__ import annotations

from typing import Iterator

from solidlsp.ls_types import SymbolKind, UnifiedSymbolInformation


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def flatten_tree(
    symbols: list[UnifiedSymbolInformation],
) -> Iterator[UnifiedSymbolInformation]:
    """Recursively yield all symbols in the tree (pre-order)."""
    for sym in symbols:
        yield sym
        children = sym.get("children", [])
        if children:
            yield from flatten_tree(children)


def format_location(sym: UnifiedSymbolInformation) -> str:
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


def format_location_str(relative_path: str, start_line: int, end_line: int) -> str:
    """Format a location string from explicit parts.

    Thin convenience for callers that already have the components extracted.
    """
    return f"{relative_path}:{start_line}-{end_line}"


def format_overview_symbols(
    symbols: list[UnifiedSymbolInformation],
    max_depth: int,
    current_depth: int,
    included_kinds: set[int] | None = None,
) -> str:
    """Format symbols as ``Kind Name:startLine-endLine`` with 2-space indent.

    When *included_kinds* is given, only symbols whose kind is in the set
    are included.  Excluding a symbol also excludes its children subtree.
    """
    lines: list[str] = []
    indent = "  " * current_depth
    for sym in symbols:
        if included_kinds is not None and sym["kind"] not in included_kinds:
            continue

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
                    format_overview_symbols(
                        children, max_depth, current_depth + 1, included_kinds
                    )
                )
    return "\n".join(lines)


def parse_kinds(raw_kinds: list[object] | None) -> set[int] | None:
    """Parse a kinds list (LSP SymbolKind names or integers) into a set of ints.

    Returns ``None`` when *raw_kinds* is ``None`` (meaning "no filter").
    Raises ``ValueError`` for unknown kind names.
    """
    if raw_kinds is None:
        return None
    result: set[int] = set()
    for k in raw_kinds:
        if isinstance(k, str):
            try:
                result.add(SymbolKind[k].value)
            except KeyError:
                raise ValueError(f"Unknown SymbolKind name: {k!r}")
        else:
            result.add(int(k))
    return result


def filter_imported_symbols(
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
                filtered[k] = filter_imported_symbols(v, imported_names)
            else:
                filtered[k] = v
        result.append(filtered)  # type: ignore[arg-type]
    return result


def extract_hover_text(hover: object) -> str:
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
