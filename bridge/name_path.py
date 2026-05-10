"""
name_path computation, matching, and unique-symbol resolution on top of
SolidLSP's ``UnifiedSymbolInformation``.

Shared infrastructure used by every pi-serena-lsp tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solidlsp import SolidLanguageServer
    from solidlsp.ls_types import UnifiedSymbolInformation


# ---------------------------------------------------------------------------
# compute_name_path
# ---------------------------------------------------------------------------

def compute_name_path(symbol: UnifiedSymbolInformation) -> str:
    """Walk the ``parent`` chain of *symbol* and return a ``/``-separated path.

    Example: ``SubprocessTransport/send`` for a method ``send`` inside a class
    ``SubprocessTransport``.  When ``overload_idx`` is present, a ``[N]`` suffix
    is appended (e.g. ``send[0]``).

    File nodes (kind 2) and package nodes (kind 4) are **not** included in the
    path — only named source symbols.
    """
    from solidlsp.ls_types import SymbolKind  # late import to avoid circular dependency at module level

    parts: list[str] = []
    node: UnifiedSymbolInformation | None = symbol

    while node is not None:
        kind = node.get("kind")
        if kind is not None and kind in (SymbolKind.File, SymbolKind.Package):
            node = node.get("parent")
            continue

        name = node.get("name", "")
        overload_idx = node.get("overload_idx")
        if overload_idx is not None:
            name = f"{name}[{overload_idx}]"
        parts.append(name)
        node = node.get("parent")

    parts.reverse()
    return "/".join(parts)


# ---------------------------------------------------------------------------
# NamePathMatcher
# ---------------------------------------------------------------------------

class NamePathMatcher:
    """Match a *path* pattern against computed ``name_path`` strings.

    Matching is component-by-component, right-to-left, each component exact:

    * ``"send"`` matches any symbol whose last component is ``send``.
    * ``"SubprocessTransport/send"`` matches symbols whose last two components
      are ``SubprocessTransport`` *and* ``send``.
    * ``"/SubprocessTransport/send"`` (leading ``/``) requires an exact full match.

    The pattern components themselves may include ``[N]`` overload indices.
    """

    def __init__(self, pattern: str) -> None:
        self._absolute = pattern.startswith("/")
        if self._absolute:
            pattern = pattern[1:]
        self._pattern_parts = [c for c in pattern.split("/") if c] if pattern else []

    def matches(self, name_path: str) -> bool:
        """Return ``True`` if *name_path* is matched by this matcher's pattern."""
        name_parts = [c for c in name_path.split("/") if c]

        if self._absolute:
            # Exact full match required
            if len(name_parts) != len(self._pattern_parts):
                return False
            return name_parts == self._pattern_parts

        if len(self._pattern_parts) > len(name_parts):
            return False

        # Right-to-left component comparison
        for p, n in zip(self._pattern_parts[::-1], name_parts[::-1]):
            if p != n:
                return False
        return True

    def __repr__(self) -> str:
        return f"NamePathMatcher({self._pattern_parts!r}, absolute={self._absolute})"


# ---------------------------------------------------------------------------
# resolve_unique_symbol
# ---------------------------------------------------------------------------

class SymbolResolutionError(Exception):
    """Raised when a symbol cannot be uniquely resolved from a ``name_path``."""

    def __init__(self, name_path: str, message: str, candidates: list[dict[str, object]] | None = None) -> None:
        super().__init__(message)
        self.name_path = name_path
        self.candidates = candidates or []

    def __str__(self) -> str:
        return f"Symbol resolution error for '{self.name_path}': {super().__str__()}"


def resolve_unique_symbol(
    ls: SolidLanguageServer,
    name_path: str,
    relative_path: str | None = None,
) -> UnifiedSymbolInformation:
    """Resolve *name_path* to a unique ``UnifiedSymbolInformation``.

    1. Call ``request_full_symbol_tree`` (scoped to *relative_path* if given).
    2. Flatten the tree.
    3. Match every symbol's computed name_path against *name_path* via
       ``NamePathMatcher``.
    4. If exactly one candidate → return it.
    5. If multiple candidates, try an exact ``compute_name_path`` match.
       If still ambiguous → raise ``SymbolResolutionError`` with candidate list.
    6. If zero candidates → raise ``SymbolResolutionError``.

    :param ls: a started ``SolidLanguageServer`` instance.
    :param name_path: the name_path pattern to search for.
    :param relative_path: optional file or directory to scope the search.
    :raises SymbolResolutionError: on ambiguity or no match.
    """
    from solidlsp.ls_types import SymbolKind  # noqa: F811

    tree = ls.request_full_symbol_tree(within_relative_path=relative_path)

    # Flatten the tree, skipping File and Package nodes in the result set
    # (they always match too broadly and are never what callers want to resolve).
    candidates: dict[str, list[UnifiedSymbolInformation]] = {}
    matcher = NamePathMatcher(name_path)

    def _collect(symbol: UnifiedSymbolInformation) -> None:
        kind = symbol.get("kind")
        if kind is not None and kind in (SymbolKind.File, SymbolKind.Package):
            for child in symbol.get("children", []):
                _collect(child)
            return

        computed = compute_name_path(symbol)
        if matcher.matches(computed):
            candidates.setdefault(computed, []).append(symbol)

        for child in symbol.get("children", []):
            _collect(child)

    for root in tree:
        _collect(root)

    all_candidates: list[UnifiedSymbolInformation] = []
    for lst in candidates.values():
        all_candidates.extend(lst)

    if len(all_candidates) == 1:
        return all_candidates[0]

    if len(all_candidates) > 1:
        # Try exact match to break the tie.
        # Strip leading "/" from pattern for comparison (name_paths never have it).
        normalized_pattern = name_path[1:] if name_path.startswith("/") else name_path
        exact_matches = [s for s in all_candidates if compute_name_path(s) == normalized_pattern]
        if len(exact_matches) == 1:
            return exact_matches[0]

        # Build a human-readable candidate list
        candidate_list: list[dict[str, object]] = []
        for s in all_candidates:
            location = s.get("location") or {}
            candidate_list.append({
                "name_path": compute_name_path(s),
                "kind": s.get("kind"),
                "location": (
                    f"{location.get('relativePath', '')}:"
                    f"{location.get('range', {}).get('start', {}).get('line', 0)}-"
                    f"{location.get('range', {}).get('end', {}).get('line', 0)}"
                ),
            })

        raise SymbolResolutionError(
            name_path,
            f"Ambiguous name_path — {len(all_candidates)} matches. Refine via find_symbol first.",
            candidates=candidate_list,
        )

    raise SymbolResolutionError(
        name_path,
        "No symbol matches this name_path in the project.",
    )


# ---------------------------------------------------------------------------
# resolve_unique_symbol_via_workspace
# ---------------------------------------------------------------------------


def resolve_unique_symbol_via_workspace(
    ls: SolidLanguageServer,
    name_path: str,
    relative_path: str | None = None,
) -> UnifiedSymbolInformation:
    """Resolve *name_path* to a unique symbol using ``workspace/symbol``.

    Avoids the expensive ``request_full_symbol_tree`` scan used by
    :func:`resolve_unique_symbol`.  Works by:

    1. Querying the LSP's ``workspace/symbol`` with the last component of
       *name_path* to get candidate symbols (fast — LSP-side index).
    2. For each candidate, calling ``request_symbol_at_location`` to get the
       full symbol with parent chain.
    3. Computing the ``name_path`` via :func:`compute_name_path` and matching
       with :class:`NamePathMatcher`.
    4. Resolving to a unique symbol (same disambiguation logic as
       :func:`resolve_unique_symbol`).

    If ``workspace/symbol`` is not supported by the language server (returns
    ``None`` or raises), falls back to :func:`resolve_unique_symbol`.

    :param ls: a started ``SolidLanguageServer`` instance.
    :param name_path: the name_path pattern to search for.
    :param relative_path: optional file or directory to scope the search.
    :raises SymbolResolutionError: on ambiguity or no match.
    """
    # Parse the last component from the name_path pattern
    pattern = name_path.lstrip("/")
    parts = [p for p in pattern.split("/") if p]
    last_component = parts[-1] if parts else ""

    if not last_component:
        raise SymbolResolutionError(name_path, "Empty name_path pattern")

    # Try workspace/symbol first
    try:
        candidates_raw = ls.request_workspace_symbol(last_component)
    except Exception:
        # workspace/symbol not supported — fall back to full tree
        return resolve_unique_symbol(ls, name_path, relative_path)

    if candidates_raw is None:
        # workspace/symbol not supported (returned None)
        return resolve_unique_symbol(ls, name_path, relative_path)

    if not candidates_raw:
        raise SymbolResolutionError(
            name_path,
            f"No symbols found matching '{last_component}' via workspace/symbol",
        )

    from solidlsp.ls_utils import PathUtils
    from pathlib import Path

    matcher = NamePathMatcher(name_path)
    candidates: dict[str, list[UnifiedSymbolInformation]] = {}

    for raw_sym in candidates_raw:
        location = raw_sym.get("location")
        if not location:
            continue

        uri = location.get("uri", "")
        if not uri:
            continue

        # Convert URI → absolute path → project-relative path
        try:
            abs_path = PathUtils.uri_to_path(uri)
            rel_path = str(Path(abs_path).resolve().relative_to(ls.repository_root_path))
        except (ValueError, Exception):
            continue

        # Filter by relative_path if provided (handle both file and directory scopes)
        if relative_path is not None:
            norm_rel = relative_path.rstrip("/")
            if rel_path != norm_rel and not rel_path.startswith(norm_rel + "/"):
                continue

        # Get position from the LSP location
        range_info = location.get("range", {})
        if not isinstance(range_info, dict):
            continue
        start = range_info.get("start", {})
        if not isinstance(start, dict):
            continue
        line = start.get("line", 0)
        col = start.get("character", 0)

        # Get full symbol info with parent chain from this single file
        full_sym = ls.request_symbol_at_location(rel_path, line, col)
        if full_sym is None:
            continue

        computed = compute_name_path(full_sym)
        if matcher.matches(computed):
            candidates.setdefault(computed, []).append(full_sym)

    # Resolve uniqueness — same logic as resolve_unique_symbol
    all_candidates: list[UnifiedSymbolInformation] = []
    for lst in candidates.values():
        all_candidates.extend(lst)

    if len(all_candidates) == 1:
        return all_candidates[0]

    if len(all_candidates) > 1:
        # Try exact match to break the tie
        normalized_pattern = name_path[1:] if name_path.startswith("/") else name_path
        exact_matches = [s for s in all_candidates if compute_name_path(s) == normalized_pattern]
        if len(exact_matches) == 1:
            return exact_matches[0]

        # Build a human-readable candidate list
        candidate_list: list[dict[str, object]] = []
        for s in all_candidates:
            loc = s.get("location") or {}
            candidate_list.append({
                "name_path": compute_name_path(s),
                "kind": s.get("kind"),
                "location": (
                    f"{loc.get('relativePath', '')}:"
                    f"{loc.get('range', {}).get('start', {}).get('line', 0)}-"
                    f"{loc.get('range', {}).get('end', {}).get('line', 0)}"
                ),
            })

        raise SymbolResolutionError(
            name_path,
            f"Ambiguous name_path — {len(all_candidates)} matches. Refine via find_symbol first.",
            candidates=candidate_list,
        )

    raise SymbolResolutionError(
        name_path,
        "No symbol matches this name_path in the project.",
    )
