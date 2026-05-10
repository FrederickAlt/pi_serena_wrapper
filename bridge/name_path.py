"""
Name path computation for Serena symbols.

A name path is a ``/``-separated path **within a single source file** (e.g.
``MyClass/my_method``). It does **not** include a file path.

``name_path`` is always a **pattern**, not an exact identifier. It is matched
component-by-component, right-to-left, each component exact:

* ``send`` matches any symbol whose last component is ``send``
* ``MyClass/send`` matches any symbol whose last two components are
  ``MyClass`` / ``send``
* ``/MyClass/send`` (absolute, leading ``/``) requires an exact full match

For overloaded symbols the overload index is appended in brackets, e.g.
``MyClass/myMethod[0]``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solidlsp.ls_types import UnifiedSymbolInformation

# LSP SymbolKind values that act as "structural" ancestors (File, Package) —
# we stop walking parents when we hit one of these.
_STRUCTURAL_KINDS: set[int] = {1, 4}  # File=1, Package=4

_OVERLOAD_RE = re.compile(r"^(.*)\[(\d+)\]$")


def compute_name_path(symbol: UnifiedSymbolInformation) -> str:
    """Compute the name path for a symbol by walking up its parent chain.

    Stops at structural symbols (File, Package).  The path is built
    root-to-leaf even though we walk leaf-to-root.
    """
    parts: list[str] = []
    cur: UnifiedSymbolInformation | None = symbol
    while cur is not None:
        if cur.get("kind") in _STRUCTURAL_KINDS:
            break
        name = cur["name"]
        overload_idx = cur.get("overload_idx")
        if overload_idx is not None:
            name = f"{name}[{overload_idx}]"
        parts.append(name)
        cur = cur.get("parent")  # type: ignore[assignment]
    parts.reverse()
    return "/".join(parts)


def _strip_overload_idx(component: str) -> str:
    """Remove any ``[N]`` overload index from a name-path component."""
    m = _OVERLOAD_RE.match(component)
    return m.group(1) if m else component


class NamePathMatcher:
    """Pattern matcher for Serena symbol name paths.

    Matching is component-by-component, right-to-left, each component exact:

    * ``send`` matches any symbol whose last component equals ``send``
    * ``MyClass/send`` matches any symbol whose last two components equal
      ``MyClass``, ``send``
    * ``/MyClass/send`` (leading ``/``) requires an exact full match
    """

    def __init__(self, name_path: str) -> None:
        self._query = name_path
        self._absolute = name_path.startswith("/")
        q = name_path.lstrip("/")
        self._query_parts = q.split("/") if q else []

    @property
    def query(self) -> str:
        return self._query

    def matches(self, name_path: str) -> bool:
        """Return ``True`` if *name_path* matches the query pattern."""
        parts = name_path.split("/")
        if self._absolute:
            # Exact full match required
            return parts == self._query_parts
        # Right-to-left component match: last N components must equal query
        n = len(self._query_parts)
        if n == 0:
            return False
        return parts[-n:] == self._query_parts

    def last_symbol_text(self) -> str:
        """Return the last component of the query name path (without overload index)."""
        if not self._query_parts:
            return ""
        return _strip_overload_idx(self._query_parts[-1])


def resolve_unique_symbol(
    symbols: list[UnifiedSymbolInformation],
    matcher: NamePathMatcher,
) -> UnifiedSymbolInformation | None:
    """Return the unique symbol whose name path matches *matcher*, or ``None``.

    Raises ``ValueError`` if more than one symbol matches.
    """
    matches: list[UnifiedSymbolInformation] = []
    for sym in symbols:
        if matcher.matches(compute_name_path(sym)):
            matches.append(sym)
    if len(matches) > 1:
        raise ValueError(
            f"Multiple symbols match name path '{matcher.query}'"
        )
    return matches[0] if matches else None
