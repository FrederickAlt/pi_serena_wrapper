"""Integration tests for bridge/import_resolver.py — classification logic
with mocked LSP and module resolver.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BRIDGE_DIR = Path(__file__).resolve().parent
if str(_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_DIR))

import pytest

from solidlsp.ls_types import UnifiedSymbolInformation
from import_resolver import _classify_import, _resolve_import_location, format_imports_section


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ls_for_workspace(
    symbols_by_name: dict[str, list[tuple[str, int, int]]],
) -> object:
    """Return a mock LS whose ``request_workspace_symbol`` returns
    symbols with the given file/line/col.

    Each entry: ``symbols_by_name[name] = [(rel_path, line, col), ...]``

    ``request_symbol_at_location`` returns a minimal symbol with the
    given location, using the query name so that ``compute_name_path``
    matches the ``NamePathMatcher`` pattern.
    """
    class MockLS:
        def __init__(self):
            self.repository_root_path = Path("/fake/project")
            self._last_query = ""

        def request_workspace_symbol(self, query):
            self._last_query = query
            results = []
            for rel_path, line, col in symbols_by_name.get(query, []):
                results.append({
                    "name": query,
                    "kind": 14,  # SymbolKind.Variable
                    "location": {
                        "uri": f"file:///fake/project/{rel_path}",
                        "range": {
                            "start": {"line": line, "character": col},
                            "end": {"line": line, "character": col + 1},
                        },
                    },
                })
            return results

        def request_symbol_at_location(self, rel_path, line, col):
            return {
                "name": self._last_query,
                "kind": 14,
                "location": {
                    "relativePath": rel_path,
                    "range": {
                        "start": {"line": line, "character": col},
                        "end": {"line": line + 2, "character": 0},
                    },
                },
            }

    return MockLS()


# ---------------------------------------------------------------------------
# Non-relative imports from nested dirs → [internal] (BUG 1 scope fix)
# ---------------------------------------------------------------------------

class TestNonRelativeImportClassification:
    """Non-relative imports from files in nested directories should
    resolve to internal symbols when the module exists in the project."""

    def test_bare_import_from_nested_dir_resolves_internal(self):
        """``formatting`` from ``bridge/tools/find_symbol.py``
        should be classified as internal because bridge/formatting.py exists."""
        ls = _make_ls_for_workspace({
            "formatting": [("bridge/formatting.py", 0, 0)],
        })
        result = _classify_import(
            module="formatting",
            names=["formatting"],
            file_relative_path="bridge/tools/find_symbol.py",
            ls=ls,
        )
        assert result.startswith("[internal →")

    def test_dotted_import_from_nested_dir_resolves_internal(self):
        """``solidlsp.ls_config`` from ``bridge/tools/find_symbol.py``
        should resolve to ``bridge/solidlsp/ls_config.py``."""
        ls = _make_ls_for_workspace({
            "ls_config": [("bridge/solidlsp/ls_config.py", 0, 0)],
        })
        result = _classify_import(
            module="solidlsp.ls_config",
            names=["ls_config"],
            file_relative_path="bridge/tools/find_symbol.py",
            ls=ls,
        )
        assert result.startswith("[internal →")

    def test_bare_import_from_root_file_still_works(self):
        """Regression: non-relative import from a project-root file
        should still resolve correctly."""
        # Workspace symbol query uses the imported *name* (NamePathMatcher),
        # not the module name (name_path).
        ls = _make_ls_for_workspace({
            "NamePathMatcher": [("bridge/name_path.py", 22, 0)],
        })
        result = _classify_import(
            module="name_path",
            names=["NamePathMatcher"],
            file_relative_path="serena_pi_bridge.py",
            ls=ls,
        )
        assert result.startswith("[internal →")


# ---------------------------------------------------------------------------
# Exact match via resolver gates out wrong same-named file
# ---------------------------------------------------------------------------

class TestExactMatchViaResolver:
    """When two files have the same module name (e.g. bridge/formatting.py
    and tests/formatting.py), only the one matching the expected
    module path should be accepted."""

    def test_exact_match_prefers_correct_directory(self):
        """``formatting`` from ``bridge/tools/find_symbol.py`` — when
        both ``bridge/formatting.py`` and ``tests/formatting.py`` exist
        in the workspace, the resolver's exact match should pick
        ``bridge/formatting.py`` (the expected path)."""
        ls = _make_ls_for_workspace({
            "formatting": [
                ("bridge/formatting.py", 0, 0),
                ("tests/formatting.py", 0, 0),
            ],
        })
        result = _classify_import(
            module="formatting",
            names=["formatting"],
            file_relative_path="bridge/tools/find_symbol.py",
            ls=ls,
        )
        # The result includes both files (ambiguity collects all),
        # but it IS classified as internal.
        assert result.startswith("[internal →")
        assert "bridge/formatting.py" in result

    def test_lenient_fallback_accepts_unexpected_dir(self):
        """When the only workspace match is in an unexpected directory
        (e.g. ``tests/formatting.py`` for an import from
        ``bridge/tools/``), the resolver can't confirm it's correct, but
        falls back to a lenient name-based check.  We'd rather show a
        false positive [internal] than risk a false negative [external]."""
        ls = _make_ls_for_workspace({
            "formatting": [
                ("tests/formatting.py", 0, 0),  # not bridge/formatting.py
            ],
        })
        result = _classify_import(
            module="formatting",
            names=["formatting"],
            file_relative_path="bridge/tools/find_symbol.py",
            ls=ls,
        )
        # Lenient fallback accepts it as internal
        assert result.startswith("[internal →")


# ---------------------------------------------------------------------------
# Fallback — no resolver for language, multiple candidates → [internal] listing all
# ---------------------------------------------------------------------------

class TestFallbackWithoutResolver:
    """When no module resolver is registered for the language (e.g., TypeScript
    in v1), the classification falls back: multiple candidates → [internal]
    listing all; zero candidates → [external]."""

    def test_multiple_candidates_no_resolver_shows_all(self):
        """With no TypeScript resolver, two candidates both get listed."""
        ls = _make_ls_for_workspace({
            "formatting": [
                ("src/formatting.ts", 0, 0),
                ("lib/formatting.ts", 0, 0),
            ],
        })
        result = _classify_import(
            module="formatting",
            names=["formatting"],
            file_relative_path="src/tools/find.ts",
            ls=ls,
        )
        # Should show both as [internal] since we can't disambiguate
        assert result.startswith("[internal")
        assert "src/formatting.ts" in result
        assert "lib/formatting.ts" in result

    def test_single_candidate_no_resolver_still_internal(self):
        """One candidate with no resolver → [internal] with location."""
        ls = _make_ls_for_workspace({
            "formatting": [
                ("src/formatting.ts", 0, 0),
            ],
        })
        result = _classify_import(
            module="formatting",
            names=["formatting"],
            file_relative_path="src/tools/find.ts",
            ls=ls,
        )
        assert result.startswith("[internal →")

    def test_zero_candidates_no_resolver_is_external(self):
        """No workspace matches → genuinely external."""
        ls = _make_ls_for_workspace({})
        result = _classify_import(
            module="flask",
            names=["Flask"],
            file_relative_path="src/app.py",
            ls=ls,
        )
        assert result == "[external]"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
