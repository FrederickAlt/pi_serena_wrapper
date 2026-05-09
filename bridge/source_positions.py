"""Source position resolution for Serena bridge tools.

Extracted from the Bridge class to enable independent testing and
a seam for alternative resolution strategies.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def find_all_offsets(content: str, needle: str) -> list[int]:
    """Find all zero-based start offsets of *needle* in *content*."""
    if not needle:
        raise ValueError("code_snippet must not be empty.")
    starts: list[int] = []
    start = content.find(needle)
    while start != -1:
        starts.append(start)
        start = content.find(needle, start + 1)
    if not starts:
        raise ValueError("code_snippet was not found in relative_path.")
    return starts


def line_col_for_offset(content: str, offset: int) -> tuple[int, int]:
    """Convert a zero-based offset to (0-based line, 0-based column)."""
    before = content[:offset]
    line = before.count("\n")
    last_newline = before.rfind("\n")
    col = offset if last_newline == -1 else offset - last_newline - 1
    return line, col


def position_spans_line(start_line: int, end_line: int, line: int) -> bool:
    """Does the range [start_line, end_line] span *line*? All 0-based."""
    return start_line <= line <= end_line


def position_contains_line_column(
    start_line: int, start_col: int,
    end_line: int, end_col: int,
    line: int, column: int,
) -> bool:
    """Does the symbol range [start_line:start_col .. end_line:end_col]
    contain the given (line, column)? All 0-based."""
    if line < start_line or line > end_line:
        return False
    if start_line == end_line:
        return start_col <= column < end_col
    if line == start_line:
        return column >= start_col
    if line == end_line:
        return column < end_col
    return True


def resolve_all_source_positions(
    file_content: str,
    code_snippet: str,
    symbol_text: str,
    line: int | None = None,
    column: int | None = None,
) -> list[tuple[int, int]]:
    """Given the full *file_content*, locate every occurrence of
    *code_snippet*, then find *symbol_text* inside each snippet occurrence
    and return its (0-based line, 0-based column) position.

    Parameters *line* and *column* are **1-based** user-facing values.
    Pass None to skip that filter.
    """
    starts = find_all_offsets(file_content, code_snippet)
    # Convert from 1-based (user-facing) to 0-based (internal)
    adjusted_line = line - 1 if line is not None else None
    adjusted_column = column - 1 if column is not None else None
    positions: list[tuple[int, int]] = []
    token_pattern = re.compile(r'\b' + re.escape(symbol_text) + r'\b')
    for start in starts:
        target_matches = list(token_pattern.finditer(code_snippet))
        if len(target_matches) == 0:
            raise ValueError(
                f"symbol_text '{symbol_text}' was not found as a complete token "
                "inside code_snippet. Use a larger symbol_text or a smaller "
                "code_snippet around the symbol if needed."
            )
        if len(target_matches) > 1:
            raise ValueError(
                f"symbol_text '{symbol_text}' appears {len(target_matches)} times "
                "as a complete token inside code_snippet. Use a smaller "
                "code_snippet around the symbol if needed."
            )
        target_start = target_matches[0].start()
        snippet_start_line, snippet_start_col = line_col_for_offset(file_content, start)
        snippet_end_line, snippet_end_col = line_col_for_offset(file_content, start + len(code_snippet))
        symbol_offset = start + target_start
        symbol_line, symbol_col = line_col_for_offset(file_content, symbol_offset)
        symbol_end_line, symbol_end_col = line_col_for_offset(file_content, symbol_offset + len(symbol_text))
        if adjusted_line is not None and not position_spans_line(
            snippet_start_line, snippet_end_line, adjusted_line,
        ):
            continue
        if adjusted_column is not None:
            if adjusted_line is None:
                raise ValueError("line must be provided when column is provided.")
            if not position_contains_line_column(
                symbol_line, symbol_col, symbol_end_line, symbol_end_col,
                adjusted_line, adjusted_column,
            ):
                continue
        positions.append((symbol_line, symbol_col))
    if not positions:
        if line is not None or column is not None:
            raise ValueError(
                "code_snippet was found, but no occurrence matched the provided "
                "line/column filters. Line/column values are 1-based."
            )
        raise ValueError("No source positions were resolved from code_snippet and symbol_text.")
    return positions
