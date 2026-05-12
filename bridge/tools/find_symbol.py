"""``find_symbol`` tool — search the symbol tree by name_path pattern."""

from __future__ import annotations

import formatting
import snippet_filter

from name_path import NamePathMatcher, collect_matching_symbols, compute_name_path
from solidlsp.ls_types import SymbolKind
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
    kinds_set: set[int] | None = None
    raw_kinds = params.get("kinds")
    if raw_kinds is not None and isinstance(raw_kinds, list):
        kinds_set = formatting.parse_kinds(raw_kinds)  # type: ignore[arg-type]
    max_matches = int(params.get("max_matches", 10))

    matcher = NamePathMatcher(name_path_str)
    ls_instances = ctx.ls_list_for(relative_path)

    # 1. Walk the full symbol tree and collect matches by name_path pattern.
    matched: list[tuple[str, object]] = []
    for ls in ls_instances:
        matched.extend(
            collect_matching_symbols(
                ls, matcher, relative_path, ctx.exclude_dot_paths,
            )
        )

    # 2. Apply kinds filter.
    if kinds_set is not None:
        matched = [(np, s) for np, s in matched if s["kind"] in kinds_set]

    # 3. Apply code-snippet filter via rg.
    if code_snippet is not None:
        filtered = snippet_filter.filter_by_snippet(
            [s for _, s in matched], code_snippet,
            cwd=ctx.cwd,
            within_path=str(relative_path) if relative_path else None,
        )
        matched = [(compute_name_path(s), s) for s in filtered]

    # 4. Truncate to max_matches (with sentinel).
    truncated = False
    if max_matches != -1 and len(matched) > max_matches:
        truncated = True
        matched = matched[:max_matches]

    # 5. Format results.
    result_symbols: list[dict[str, object]] = []
    for np, sym in matched:
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
