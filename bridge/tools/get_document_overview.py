"""``get_document_overview`` tool — two-section plain-text overview of a source file."""

from __future__ import annotations

import formatting
import import_resolver
from import_parser import parse_imports
from path_validation import validate_project_path
from solidlsp.ls_types import SymbolKind
from tool_context import ToolContext


def get_document_overview(params: dict[str, object], ctx: ToolContext) -> str:
    """Return a two-section plain-text overview: Imports + Symbols.

    Imports are grouped by source module and classified as ``[internal]``
    or ``[external]``.  Symbols show ``Kind Name:startLine-endLine`` with
    2-space indentation.
    """
    relative_path = str(params["relative_path"])
    depth = int(params.get("depth", 0))

    raw_kinds = params.get("kinds")
    if raw_kinds is not None and isinstance(raw_kinds, list):
        included_kinds = formatting.parse_kinds(raw_kinds)
    else:
        included_kinds = set(ctx.overview_kinds)

    abs_path = validate_project_path(relative_path, ctx.cwd)
    if not abs_path.is_file():
        raise FileNotFoundError(f"File not found: {relative_path}")
    source = abs_path.read_text(encoding="utf-8")

    file_language = ctx.language_for_file(relative_path)
    ls = ctx.ls_for_file(relative_path)

    import_pairs = parse_imports(source, file_language)

    sections: list[str] = []

    if import_pairs:
        imports_section = import_resolver.format_imports_section(import_pairs, relative_path, ls)
        sections.append("## Imports")
        sections.append(imports_section)

    doc_symbols = ls.request_document_symbols(relative_path)
    imported_names: set[str] = {binding for _, binding, _ in import_pairs}

    if doc_symbols is None:
        filtered_root_symbols = []
    else:
        filtered_root_symbols = formatting.filter_imported_symbols(
            doc_symbols.root_symbols, imported_names
        )

    # Flatten, truncate, and format symbols.
    max_matches = int(params.get("max_matches", -1))
    flattened = formatting.flatten_tree_filtered(
        filtered_root_symbols, depth, 0, included_kinds
    )

    truncated = False
    if max_matches > 0 and len(flattened) > max_matches:
        truncated = True
        flattened = flattened[:max_matches]

    symbol_lines: list[str] = []
    for d, sym in flattened:
        indent = "  " * d
        kind_name = SymbolKind(sym["kind"]).name
        name = sym["name"]
        rng = sym.get("range") or {}
        start_line = rng.get("start", {}).get("line", 0) + 1
        end_line = rng.get("end", {}).get("line", 0) + 1
        symbol_lines.append(f"{indent}{kind_name} {name}:{start_line}-{end_line}")

    if truncated:
        symbol_lines.append("...")

    symbols_text = "\n".join(symbol_lines)
    sections.append("## Symbols")
    sections.append(symbols_text)

    return "\n".join(sections)
