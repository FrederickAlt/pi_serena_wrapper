"""
name_path computation, matching, and unique-symbol resolution on top of
SolidLSP's ``UnifiedSymbolInformation``.

Shared infrastructure used by every pi-serena-lsp tool.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solidlsp import SolidLanguageServer
    from solidlsp.ls_types import UnifiedSymbolInformation


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _is_dot_path(relative_path: str) -> bool:
    """Return ``True`` if *relative_path* contains a dot-prefixed directory component.

    Dot-prefixed directories are hidden / metadata directories like
    ``.venv``, ``.git``, ``.sandcastle``, ``.solidlsp``, etc.
    """
    if not relative_path:
        return False
    # Normalize: strip leading ./ and handle root-edge cases
    normalized = relative_path.lstrip("./") or "."
    return any(part.startswith(".") for part in Path(normalized).parts)


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


def _disambiguate(
    candidates: dict[str, list[UnifiedSymbolInformation]],
    name_path: str,
) -> UnifiedSymbolInformation:
    """Resolve a *candidates* dict (keyed by computed name_path) to a unique symbol.

    Shared by :func:`resolve_unique_symbol` and
    :func:`resolve_unique_symbol_via_workspace` — both build candidate dicts
    differently but resolve them the same way.

    Returns the unique symbol on success.  Raises ``SymbolResolutionError``
    with a candidate list on ambiguity, or with a "no match" message when
    *candidates* is empty.
    """
    from solidlsp.ls_types import SymbolKind

    all_candidates: list[UnifiedSymbolInformation] = []
    for lst in candidates.values():
        all_candidates.extend(lst)

    if len(all_candidates) == 1:
        return all_candidates[0]

    if len(all_candidates) > 1:
        # Try exact match to break the tie.
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
                "kind": SymbolKind(s.get("kind")).name,
                "location": (
                    f"{location.get('relativePath', '')}:"
                    f"{location.get('range', {}).get('start', {}).get('line', 0) + 1}-"
                    f"{location.get('range', {}).get('end', {}).get('line', 0) + 1}"
                ),
            })

        raise SymbolResolutionError(
            name_path,
            f"Ambiguous name_path — {len(all_candidates)} matches. Refine via find_symbol first.",
            candidates=candidate_list,
        )

    raise SymbolResolutionError(
        name_path,
        f"No symbol matches '{name_path}' in the project.",
    )


def collect_matching_symbols(
    ls: SolidLanguageServer,
    matcher: NamePathMatcher,
    relative_path: str | None = None,
    exclude_dot_paths: bool = False,
) -> list[tuple[str, UnifiedSymbolInformation]]:
    """Return ``(name_path, symbol)`` for every symbol in the full tree that
    matches *matcher*.

    Shared by :func:`find_symbol` (which adds code-snippet / kinds /
    max-matches filtering) and :func:`resolve_unique_symbol` (which routes
    results through :func:`_disambiguate`).

    File and Package nodes are skipped — they match too broadly.
    Dot-prefixed directories (``.venv``, ``.git``, etc.) are optionally
    excluded.
    """
    from solidlsp.ls_types import SymbolKind
    import formatting

    tree = ls.request_full_symbol_tree(within_relative_path=relative_path)
    matched: list[tuple[str, UnifiedSymbolInformation]] = []

    for sym in formatting.flatten_tree(tree):
        kind = sym.get("kind")
        if kind is not None and kind in (SymbolKind.File, SymbolKind.Package):
            continue

        if exclude_dot_paths:
            loc = sym.get("location") or {}
            rel_path = loc.get("relativePath")
            if rel_path and _is_dot_path(str(rel_path)):
                continue

        np = compute_name_path(sym)
        if matcher.matches(np):
            matched.append((np, sym))

    return matched


def resolve_unique_symbol(
    ls: SolidLanguageServer,
    name_path: str,
    relative_path: str | None = None,
    exclude_dot_paths: bool = False,
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
    :param exclude_dot_paths: if ``True``, symbols from dot-prefixed directories
        (``.venv``, ``.git``, etc.) are excluded.
    :raises SymbolResolutionError: on ambiguity or no match.
    """
    if not name_path.strip():
        raise SymbolResolutionError(name_path, "name_path must not be empty or whitespace-only")

    matcher = NamePathMatcher(name_path)
    matched = collect_matching_symbols(ls, matcher, relative_path, exclude_dot_paths)

    candidates: dict[str, list[UnifiedSymbolInformation]] = {}
    for np, sym in matched:
        candidates.setdefault(np, []).append(sym)

    return _disambiguate(candidates, name_path)


# ---------------------------------------------------------------------------
# resolve_unique_symbol_via_workspace
# ---------------------------------------------------------------------------


def _merge_fallback_candidates(
    candidates: dict[str, list[UnifiedSymbolInformation]],
    ls: SolidLanguageServer,
    name_path: str,
    relative_path: str | None,
    exclude_dot_paths: bool,
) -> None:
    """Fall back to :func:`resolve_unique_symbol` on *ls* and merge result.

    If :func:`resolve_unique_symbol` succeeds (single match), the result is
    added to *candidates* under its computed name_path.  If it raises
    ``SymbolResolutionError`` with candidates (ambiguity), the error is
    re-raised so the caller can report it.  If it raises with zero candidates,
    the error is silently ignored (another language server may succeed).
    """
    try:
        result = resolve_unique_symbol(ls, name_path, relative_path, exclude_dot_paths=exclude_dot_paths)
        computed = compute_name_path(result)
        candidates.setdefault(computed, []).append(result)
    except SymbolResolutionError as exc:
        if exc.candidates:
            raise  # Re-raise ambiguity so the caller can report it
        # Zero candidates — ignore, another LS may succeed


def resolve_unique_symbol_via_workspace(
    ls_list: list[SolidLanguageServer],
    name_path: str,
    relative_path: str | None = None,
    exclude_dot_paths: bool = False,
) -> UnifiedSymbolInformation:
    """Resolve *name_path* to a unique symbol using ``workspace/symbol``.

    Avoids the expensive ``request_full_symbol_tree`` scan used by
    :func:`resolve_unique_symbol`.  Works by:

    1. Querying each language server's ``workspace/symbol`` with the last
       component of *name_path* to get candidate symbols (fast — LSP-side index).
    2. For each candidate, calling ``request_symbol_at_location`` to get the
       full symbol with parent chain.
    3. Computing the ``name_path`` via :func:`compute_name_path` and matching
       with :class:`NamePathMatcher`.
    4. Resolving to a unique symbol (same disambiguation logic as
       :func:`resolve_unique_symbol`).

    If ``workspace/symbol`` is not supported by a language server (returns
    ``None`` or raises), falls back to :func:`resolve_unique_symbol` for that
    server.

    :param ls_list: one or more started ``SolidLanguageServer`` instances.
        Callers should pass ``[ls_for_file]`` when *relative_path* scopes to a
        single file, or all LS instances when searching project-wide.
    :param name_path: the name_path pattern to search for.
    :param relative_path: optional file or directory to scope the search.
    :param exclude_dot_paths: if ``True``, symbols from dot-prefixed directories
        (``.venv``, ``.git``, etc.) are excluded.
    :raises SymbolResolutionError: on ambiguity or no match.
    """
    # Parse the last component from the name_path pattern
    pattern = name_path.lstrip("/")
    parts = [p for p in pattern.split("/") if p]
    last_component = parts[-1] if parts else ""

    if not name_path.strip():
        raise SymbolResolutionError(name_path, "name_path must not be empty or whitespace-only")

    if not last_component:
        raise SymbolResolutionError(name_path, "Empty name_path pattern")

    if not ls_list:
        raise SymbolResolutionError(name_path, "No language servers available")

    from solidlsp.ls_utils import PathUtils
    from solidlsp.ls_types import SymbolKind  # noqa: F811

    matcher = NamePathMatcher(name_path)
    candidates: dict[str, list[UnifiedSymbolInformation]] = {}

    for ls in ls_list:
        # Try workspace/symbol first
        try:
            candidates_raw = ls.request_workspace_symbol(last_component)
        except Exception:
            # workspace/symbol not supported — fall back to full tree for this LS
            _merge_fallback_candidates(
                candidates, ls, name_path, relative_path, exclude_dot_paths
            )
            continue

        if candidates_raw is None:
            # workspace/symbol not supported (returned None)
            _merge_fallback_candidates(
                candidates, ls, name_path, relative_path, exclude_dot_paths
            )
            continue

        if not candidates_raw:
            # Empty list means workspace/symbol returned no results for this
            # query, but the symbol may still be in the full tree.  Fall back
            # to resolve_unique_symbol so it can find it.
            _merge_fallback_candidates(
                candidates, ls, name_path, relative_path, exclude_dot_paths
            )
            continue

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

            # Apply dot-path filtering if enabled
            if exclude_dot_paths and _is_dot_path(rel_path):
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

            # Apply dot-path filtering again (full_sym location may differ)
            if exclude_dot_paths:
                full_loc = full_sym.get("location") or {}
                full_rel = full_loc.get("relativePath")
                if full_rel and _is_dot_path(str(full_rel)):
                    continue

            computed = compute_name_path(full_sym)
            if matcher.matches(computed):
                candidates.setdefault(computed, []).append(full_sym)

        # If workspace/symbol returned results but none matched after full
        # resolution (e.g. parent-chain difference, location mismatch), fall
        # back to the complete tree scan so the symbol isn't silently missed.
        if not candidates:
            _merge_fallback_candidates(
                candidates, ls, name_path, relative_path, exclude_dot_paths
            )

    return _disambiguate(candidates, name_path)
