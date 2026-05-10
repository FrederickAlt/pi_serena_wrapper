"""Shared name-path infrastructure for Serena bridge tools.

Provides utilities to compute, match, and resolve Serena symbol name paths
(e.g. ``ClassName/methodName``) against SolidLSP's UnifiedSymbolInformation tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from solidlsp.lsp_protocol_handler.lsp_types import SymbolKind

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer
    from solidlsp.ls_types import UnifiedSymbolInformation

# Symbol kinds that represent structural containers rather than code symbols.
_STRUCTURAL_KINDS: set[int] = {SymbolKind.File, SymbolKind.Package}


class SymbolResolutionError(Exception):
    """Raised when a name_path cannot be resolved to a unique symbol."""

    pass


def compute_name_path(symbol: UnifiedSymbolInformation) -> str:
    """Compute the Serena name path for *symbol* by walking up its parent chain.

    The name path consists of ``/``-separated symbol names from the outermost
    **code** symbol (skipping File and Package structural symbols) down to the
    symbol itself.

    Example: for a method ``greet`` inside class ``Greeter`` in file ``src/index.ts``
    this returns ``"Greeter/greet"``.
    """
    parts: list[str] = []
    current: UnifiedSymbolInformation | None = symbol
    while current is not None:
        kind = current.get("kind")
        if kind not in _STRUCTURAL_KINDS:
            name = current.get("name", "")
            if name:
                parts.append(name)
        current = current.get("parent")  # type: ignore[assignment]
    parts.reverse()
    return "/".join(parts)


class NamePathMatcher:
    """Match symbols against a Serena name path pattern.

    The pattern is a ``/``-separated sequence of symbol names.  Matching
    is exact and requires the full path to match from the **innermost**
    symbol outward (suffix match).
    """

    def __init__(self, name_path: str) -> None:
        self._parts = name_path.strip("/").split("/")
        if not self._parts or self._parts == [""]:
            raise ValueError(f"Invalid name_path: {name_path!r}")

    def matches(self, symbol: UnifiedSymbolInformation) -> bool:
        """Return True if *symbol*'s computed name path matches this pattern."""
        try:
            symbol_path = compute_name_path(symbol)
        except Exception:
            return False
        return symbol_path == "/".join(self._parts)


def resolve_unique_symbol(
    ls: SolidLanguageServer,
    name_path: str,
    relative_path: str | None = None,
) -> UnifiedSymbolInformation:
    """Resolve *name_path* to a single :class:`UnifiedSymbolInformation`.

    Parameters
    ----------
    ls:
        An initialised SolidLanguageServer instance.
    name_path:
        Serena name path (e.g. ``"ClassName/methodName"``).
    relative_path:
        Optional file or directory path to scope the search.  When given,
        only symbols within that scope are considered.

    Returns
    -------
    UnifiedSymbolInformation
        The unique matching symbol.

    Raises
    ------
    SymbolResolutionError
        If the name path matches zero symbols or more than one symbol.
    """
    matcher = NamePathMatcher(name_path)

    # Build the full symbol tree, scoped if a relative_path is given.
    root_symbols = ls.request_full_symbol_tree(within_relative_path=relative_path)

    matches: list[UnifiedSymbolInformation] = []

    def _walk(sym: UnifiedSymbolInformation) -> None:
        if matcher.matches(sym):
            matches.append(sym)
        for child in sym.get("children", []):
            _walk(child)

    for root in root_symbols:
        _walk(root)

    if not matches:
        scope = f" within {relative_path!r}" if relative_path else ""
        raise SymbolResolutionError(
            f"No symbol found for name_path {name_path!r}{scope}."
        )

    if len(matches) > 1:
        scope = f" within {relative_path!r}" if relative_path else ""
        locations = ", ".join(
            m.get("location", {}).get("relativePath", "?") for m in matches
        )
        raise SymbolResolutionError(
            f"Multiple symbols ({len(matches)}) match name_path "
            f"{name_path!r}{scope}: {locations}"
        )

    return matches[0]
