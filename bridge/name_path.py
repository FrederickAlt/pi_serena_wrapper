"""Name-path computation and symbol resolution for Serena bridge tools.

Shared infrastructure used by tool implementations to resolve a
human-readable ``name_path`` (e.g. ``MyClass/my_method``) to a unique symbol
in the LSP symbol tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solidlsp import SolidLanguageServer
    from solidlsp.ls_types import UnifiedSymbolInformation


class SymbolResolutionError(Exception):
    """Raised when a name_path cannot be resolved to a unique symbol."""

    def __init__(self, message: str, candidates: list[dict[str, object]] | None = None) -> None:
        super().__init__(message)
        self.candidates: list[dict[str, object]] = candidates or []


# ---------------------------------------------------------------------------
# Core name-path helpers
# ---------------------------------------------------------------------------


def compute_name_path(symbol: UnifiedSymbolInformation) -> str:
    """Compute the absolute name path for *symbol* by walking up its
    ``parent`` chain and joining ``name`` fields with ``/``.

    The result always starts with ``/`` to denote an absolute path.
    """
    parts: list[str] = []
    node: UnifiedSymbolInformation | None = symbol
    while node is not None:
        parts.append(node["name"])
        node = node.get("parent")  # type: ignore[assignment]
    parts.reverse()
    return "/" + "/".join(parts)


def _iter_all_symbols(root_symbols: list[UnifiedSymbolInformation]):
    """Depth-first iterator over every symbol in *root_symbols* (including roots)."""
    for root in root_symbols:
        yield from _traverse(root)


def _traverse(symbol: UnifiedSymbolInformation):
    yield symbol
    for child in symbol.get("children", []):
        yield from _traverse(child)


# ---------------------------------------------------------------------------
# NamePathMatcher
# ---------------------------------------------------------------------------


class NamePathMatcher:
    """Match symbols against a name_path pattern.

    A *name_path* is a ``/``-separated sequence of symbol names, e.g.
    ``MyClass/my_method``.  A leading ``/`` makes it **absolute**: the
    match must start from the root of the symbol tree.  Without the
    leading ``/`` the match is **relative** — any suffix of the symbol's
    absolute name path is accepted.
    """

    def __init__(self, name_path: str) -> None:
        if not name_path or not name_path.strip():
            raise ValueError("name_path must not be empty.")
        self.absolute = name_path.startswith("/")
        # Normalise: strip leading "/" so segments are uniform.
        cleaned = name_path.lstrip("/")
        self.segments = cleaned.split("/") if cleaned else []
        if not self.segments:
            raise ValueError(f"Invalid name_path: {name_path!r}")

    def matches(self, symbol: UnifiedSymbolInformation) -> bool:
        """Return True if *symbol* matches this matcher's name_path."""
        abs_path = compute_name_path(symbol)
        abs_segments = abs_path.split("/")  # first element is '' (leading /)
        # abs_segments = ['', 'src', 'index', 'MyClass', 'my_method']

        if self.absolute:
            # Must match exactly (modulo leading empty string).
            return abs_segments[1:] == self.segments

        # Relative: suffix match.
        if len(self.segments) > len(abs_segments) - 1:
            return False
        return abs_segments[-len(self.segments):] == self.segments


# ---------------------------------------------------------------------------
# resolve_unique_symbol
# ---------------------------------------------------------------------------


def resolve_unique_symbol(
    ls: SolidLanguageServer,
    name_path: str,
    relative_path: str | None = None,
) -> UnifiedSymbolInformation:
    """Resolve *name_path* to exactly one symbol.

    Parameters
    ----------
    ls:
        An active (started) SolidLanguageServer instance.
    name_path:
        The name path to resolve, e.g. ``MyClass/my_method`` or
        ``/MyClass/my_method``.
    relative_path:
        Optional file or directory path to scope the symbol search.

    Returns
    -------
    UnifiedSymbolInformation
        The unique matching symbol.

    Raises
    ------
    SymbolResolutionError
        If zero or more than one symbol matches.
    """
    matcher = NamePathMatcher(name_path)
    root_symbols = ls.request_full_symbol_tree(within_relative_path=relative_path)

    # Collect all matching symbols.
    matches: list[UnifiedSymbolInformation] = []
    for sym in _iter_all_symbols(root_symbols):
        if matcher.matches(sym):
            matches.append(sym)

    if len(matches) == 1:
        return matches[0]

    if len(matches) == 0:
        raise SymbolResolutionError(
            f"No symbol found matching name_path {name_path!r}."
            + (f" (within {relative_path!r})" if relative_path else ""),
            candidates=[],
        )

    # Multiple matches — build candidate list.
    candidates: list[dict[str, object]] = []
    for m in matches:
        loc = m.get("location")
        candidates.append({
            "name_path": compute_name_path(m),
            "kind": int(m["kind"]),
            "relative_path": loc.get("relativePath") if loc else None,
            "line": loc["range"]["start"]["line"] if loc else None,
            "character": loc["range"]["start"]["character"] if loc else None,
        })

    raise SymbolResolutionError(
        f"Name path {name_path!r} is ambiguous. "
        f"Found {len(matches)} matching symbols. "
        "Use a more qualified name_path.",
        candidates=candidates,
    )
