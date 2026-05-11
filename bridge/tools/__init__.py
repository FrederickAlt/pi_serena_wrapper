"""Tool registry — maps tool names to their implementation functions.

Add a new tool by importing it and adding an entry to ``TOOL_REGISTRY``.
The Bridge's ``call_tool`` dispatches through this dict.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tools.find_symbol import find_symbol
from tools.get_type import get_type
from tools.get_references import get_references
from tools.get_implementations import get_implementations
from tools.get_docstring import get_docstring
from tools.rename_symbol import rename_symbol
from tools.get_document_overview import get_document_overview

#: (params: dict, ctx: ToolContext) -> result
ToolFn = Callable[[dict[str, object], Any], object]

TOOL_REGISTRY: dict[str, ToolFn] = {
    "find_symbol": find_symbol,
    "get_type": get_type,
    "get_references": get_references,
    "get_implementations": get_implementations,
    "get_docstring": get_docstring,
    "rename_symbol": rename_symbol,
    "get_document_overview": get_document_overview,
}
