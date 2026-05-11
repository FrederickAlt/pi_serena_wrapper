"""``get_docstring`` tool — hover text for a symbol."""

from __future__ import annotations

import formatting
from tool_context import ToolContext
from resolution import resolve_tool_symbol


def get_docstring(params: dict[str, object], ctx: ToolContext) -> str:
    """Return hover text for the symbol identified by ``name_path``."""
    resolved = resolve_tool_symbol(params, ctx)

    hover = resolved.ls.request_hover(resolved.file_path, resolved.line, resolved.column)
    text = formatting.extract_hover_text(hover)
    return text if text else "No docstring available."
