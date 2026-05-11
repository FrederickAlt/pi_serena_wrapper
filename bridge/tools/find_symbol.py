"""``find_symbol`` tool — search the symbol tree by name_path pattern."""

from __future__ import annotations

import formatting
import snippet_filter

from name_path import NamePathMatcher, compute_name_path, _is_dot_path
from solidlsp.ls_types import SymbolKind, UnifiedSymbolInformation
from tool_context import ToolContext


def find_symbol(params: dict[str, object], ctx: ToolContext) -> list[dict[str, object]]:
    """Search the symbol tree by name_path pattern.

    Matched component-by-component, right-to-left, each component exact.
    Supports optional filtering by ``code_snippet`` (rg), ``kinds``, and
    ``max_matches`` (with truncation sentinel).
    """
    name_path_str = str(params["name_path"])
    if not name_path_str.strip():
        raise ValueError("name_path must not be empty or whitespace-only")
    relative_path = params.get("relative_path")
    if relative_path is not None:
        relative_path = str(relative_path)
    code_snippet = params.get("code_snippet")
    if code_snippet is not None:
        code_snippet = str(code_snippet)
    kinds: list[int] | None = None
    raw_kinds = params.get("kinds")
    if raw_kinds is not None and isinstance(raw_kinds, list):
        kinds = list(formatting.parse_kinds(raw_kinds))  # type: ignore[arg-type]
    max_matches = int(params.get("max_matches", 10))

    matcher = NamePathMatcher(name_path_str)

    ls_instances = ctx.ls_list_for(relative_path)  # type: ignore[call-arg]

    matched: list[UnifiedSymbolInformation] = []
    for ls in ls_instances:
        tree = ls.request_full_symbol_tree(
            within_relative_path=relative_path if relative_path else None
        )
        flat_symbols = list(formatting.flatten_tree(tree))
        for sym in flat_symbols:
            if ctx.exclude_dot_paths:
                loc = sym.get("location") or {}
                rel = loc.get("relativePath")
                if rel and _is_dot_path(str(rel)):
                    continue
            np = compute_name_path(sym)
            if matcher.matches(np):
                matched.append(sym)

    if code_snippet is not None:
        matched = snippet_filter.filter_by_snippet(
            matched, code_snippet,
            cwd=ctx.cwd,
            within_path=str(relative_path) if relative_path else None,
        )

    if kinds is not None:
        kinds_set = set(kinds)
        matched = [s for s in matched if s["kind"] in kinds_set]

    truncated = False
    if max_matches != -1 and len(matched) > max_matches:
        truncated = True
        matched = matched[:max_matches]

    result_symbols: list[dict[str, object]] = []
    for sym in matched:
        np = compute_name_path(sym)
        kind_name = SymbolKind(sym["kind"]).name
        loc_str = formatting.format_location(sym)
        result_symbols.append({
            "name_path": np,
            "kind": kind_name,
            "location": loc_str,
        })

    if truncated:
        result_symbols.append({
            "name_path": "--truncated--",
            "kind": "None",
            "location": "None",
        })

    return result_symbols
