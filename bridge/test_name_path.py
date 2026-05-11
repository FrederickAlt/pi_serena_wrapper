"""Unit tests for bridge/name_path.py — hand-crafted symbol trees only (no LSP needed)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

# Ensure bridge/ is importable.
_BRIDGE_DIR = Path(__file__).resolve().parent
if str(_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_DIR))

import pytest

from solidlsp.ls_types import UnifiedSymbolInformation, SymbolKind
from name_path import compute_name_path, NamePathMatcher, resolve_unique_symbol, resolve_unique_symbol_via_workspace, SymbolResolutionError


# ---------------------------------------------------------------------------
# Helpers — hand-crafted symbol trees
# ---------------------------------------------------------------------------

def _make_symbol(
    name: str,
    kind: int = SymbolKind.Method,
    *,
    children: list[UnifiedSymbolInformation] | None = None,
    parent: UnifiedSymbolInformation | None = None,
    overload_idx: int | None = None,
    location: dict | None = None,
) -> UnifiedSymbolInformation:
    """Build a minimal UnifiedSymbolInformation for testing."""
    sym: UnifiedSymbolInformation = cast(UnifiedSymbolInformation, {
        "name": name,
        "kind": kind,
        "children": children or [],
    })
    if parent is not None:
        sym["parent"] = parent
    if overload_idx is not None:
        sym["overload_idx"] = overload_idx
    if location is not None:
        sym["location"] = location
    return sym


def _link_parents(symbols: list[UnifiedSymbolInformation]) -> list[UnifiedSymbolInformation]:
    """Inline convenience: links each child's ``parent`` in a recursive tree."""
    def _walk(symbol: UnifiedSymbolInformation) -> None:
        for child in symbol.get("children", []):
            child["parent"] = symbol
            _walk(child)
    for root in symbols:
        _walk(root)
    return symbols


# ---------------------------------------------------------------------------
# compute_name_path
# ---------------------------------------------------------------------------

class TestComputeNamePath:
    def test_single_symbol_no_parent(self):
        sym = _make_symbol("send")
        assert compute_name_path(sym) == "send"

    def test_nested_with_parent(self):
        parent = _make_symbol("SubprocessTransport", kind=SymbolKind.Class)
        child = _make_symbol("send", parent=parent)
        assert compute_name_path(child) == "SubprocessTransport/send"

    def test_skips_file_and_package_nodes(self):
        pkg = _make_symbol("src", kind=SymbolKind.Package)
        file = _make_symbol("transport", kind=SymbolKind.File, parent=pkg)
        klass = _make_symbol("SubprocessTransport", kind=SymbolKind.Class, parent=file)
        method = _make_symbol("send", parent=klass)
        # File and Package should be excluded
        assert compute_name_path(method) == "SubprocessTransport/send"

    def test_with_overload_index(self):
        sym = _make_symbol("send", overload_idx=0)
        assert compute_name_path(sym) == "send[0]"

    def test_nested_with_overload(self):
        klass = _make_symbol("Foo", kind=SymbolKind.Class)
        method = _make_symbol("bar", overload_idx=2, parent=klass)
        assert compute_name_path(method) == "Foo/bar[2]"

    def test_deeply_nested(self):
        pkg = _make_symbol("pkg", kind=SymbolKind.Package)
        file = _make_symbol("mod", kind=SymbolKind.File, parent=pkg)
        outer = _make_symbol("Outer", kind=SymbolKind.Class, parent=file)
        inner = _make_symbol("Inner", kind=SymbolKind.Class, parent=outer)
        method = _make_symbol("doit", kind=SymbolKind.Method, parent=inner)
        assert compute_name_path(method) == "Outer/Inner/doit"


# ---------------------------------------------------------------------------
# NamePathMatcher
# ---------------------------------------------------------------------------

class TestNamePathMatcher:
    # -- bare patterns (right-to-left suffix match) --

    def test_bare_single_matches_last(self):
        m = NamePathMatcher("send")
        assert m.matches("send")
        assert m.matches("SubprocessTransport/send")
        assert m.matches("pkg/SubprocessTransport/send")

    def test_bare_single_no_match_wrong_name(self):
        m = NamePathMatcher("send")
        assert not m.matches("receive")
        assert not m.matches("SubprocessTransport/receive")

    def test_bare_multi_suffix_match(self):
        m = NamePathMatcher("SubprocessTransport/send")
        assert m.matches("SubprocessTransport/send")
        assert m.matches("pkg/SubprocessTransport/send")
        assert not m.matches("send")  # too short
        assert not m.matches("Other/send")  # wrong second-to-last

    # -- absolute patterns --

    def test_absolute_exact_match(self):
        m = NamePathMatcher("/SubprocessTransport/send")
        assert m.matches("SubprocessTransport/send")
        assert not m.matches("pkg/SubprocessTransport/send")
        assert not m.matches("send")

    def test_absolute_root(self):
        m = NamePathMatcher("/send")
        assert m.matches("send")
        assert not m.matches("SubprocessTransport/send")

    # -- edge cases --

    def test_empty_pattern_matches_everything(self):
        m = NamePathMatcher("")
        assert m.matches("send")
        assert m.matches("")
        assert m.matches("a/b/c")

    def test_with_overload_indices(self):
        m = NamePathMatcher("send[0]")
        assert m.matches("send[0]")
        assert m.matches("Foo/send[0]")
        assert not m.matches("send[1]")

    def test_absolute_with_overload(self):
        m = NamePathMatcher("/Foo/bar[2]")
        assert m.matches("Foo/bar[2]")
        assert not m.matches("pkg/Foo/bar[2]")
        assert not m.matches("Foo/bar[0]")

    def test_pattern_longer_than_name_path(self):
        m = NamePathMatcher("A/B/C")
        assert not m.matches("B/C")
        assert not m.matches("C")

    def test_repr(self):
        assert "NamePathMatcher" in repr(NamePathMatcher("foo"))


# ---------------------------------------------------------------------------
# resolve_unique_symbol
# ---------------------------------------------------------------------------

class TestResolveUniqueSymbol:
    """Test resolve_unique_symbol using a hand-crafted symbol tree.

    We patch ``SolidLanguageServer.request_full_symbol_tree`` to return our
    constructed tree so that no real LSP is needed.
    """

    @staticmethod
    def _tree():
        """Build a small symbol tree simulating a project with two files."""
        # File 1: transport.ts
        file1 = _make_symbol("transport", kind=SymbolKind.File)
        klass = _make_symbol("SubprocessTransport", kind=SymbolKind.Class, parent=file1)
        method_send = _make_symbol("send", kind=SymbolKind.Method, parent=klass,
                                   location={"relativePath": "src/transport.ts",
                                              "range": {"start": {"line": 108, "character": 0},
                                                        "end": {"line": 130, "character": 0}}})
        method_shutdown = _make_symbol("shutdown", kind=SymbolKind.Method, parent=klass,
                                       location={"relativePath": "src/transport.ts",
                                                  "range": {"start": {"line": 140, "character": 0},
                                                            "end": {"line": 155, "character": 0}}})
        klass["children"] = [method_send, method_shutdown]
        file1["children"] = [klass]

        # File 2: main.ts — also has a "send" function, creating potential ambiguity
        file2 = _make_symbol("main", kind=SymbolKind.File)
        func_send = _make_symbol("send", kind=SymbolKind.Function, parent=file2,
                                 location={"relativePath": "src/main.ts",
                                            "range": {"start": {"line": 10, "character": 0},
                                                      "end": {"line": 20, "character": 0}}})
        func_other = _make_symbol("otherHelper", kind=SymbolKind.Function, parent=file2,
                                  location={"relativePath": "src/main.ts",
                                             "range": {"start": {"line": 30, "character": 0},
                                                       "end": {"line": 40, "character": 0}}})
        file2["children"] = [func_send, func_other]

        return [file1, file2]

    @staticmethod
    def _make_ls_mock(tree):
        """Create a minimal mock LS that returns *tree* from request_full_symbol_tree."""
        class MockLS:
            @staticmethod
            def request_full_symbol_tree(within_relative_path=None):
                return tree
        return MockLS()

    # -- single match --

    def test_unique_match_by_bare_last_component(self):
        """``send`` matches via bare single component → returns the unique ``send`` method."""
        tree = self._tree()
        ls = self._make_ls_mock(tree)
        # Only one "shutdown" exists
        result = resolve_unique_symbol(ls, "shutdown")  # type: ignore[arg-type]
        assert result["name"] == "shutdown"
        assert result["kind"] == SymbolKind.Method

    # -- multiple matches with exact tie-break --

    def test_ambiguous_with_exact_break(self):
        """``send`` matches both method and function, but
        ``SubprocessTransport/send`` is exact for one."""
        tree = self._tree()
        ls = self._make_ls_mock(tree)
        result = resolve_unique_symbol(ls, "SubprocessTransport/send")  # type: ignore[arg-type]
        assert result["name"] == "send"
        assert result["kind"] == SymbolKind.Method
        assert result["location"]["relativePath"] == "src/transport.ts"

    # -- ambiguity error --

    def test_ambiguous_raises_symbol_resolution_error(self):
        """Two symbols with the same computed name_path → error with candidates."""
        # Two files each containing a top-level ``send`` function.
        file1 = _make_symbol("transport", kind=SymbolKind.File)
        send1 = _make_symbol("send", kind=SymbolKind.Function, parent=file1,
                             location={"relativePath": "src/transport.ts",
                                        "range": {"start": {"line": 10, "character": 0},
                                                  "end": {"line": 15, "character": 0}}})
        file1["children"] = [send1]

        file2 = _make_symbol("main", kind=SymbolKind.File)
        send2 = _make_symbol("send", kind=SymbolKind.Function, parent=file2,
                             location={"relativePath": "src/main.ts",
                                        "range": {"start": {"line": 5, "character": 0},
                                                  "end": {"line": 10, "character": 0}}})
        file2["children"] = [send2]

        tree = [file1, file2]
        ls = self._make_ls_mock(tree)
        with pytest.raises(SymbolResolutionError) as exc_info:
            resolve_unique_symbol(ls, "send")  # type: ignore[arg-type]
        assert "Ambiguous" in str(exc_info.value)
        assert exc_info.value.candidates
        assert len(exc_info.value.candidates) == 2

    # -- candidate location line numbers must be 1-based (Bug 1) --

    def test_disambiguation_candidates_use_one_based_lines(self):
        """Candidate locations from ambiguity errors must use 1-based line numbers.

        LSP line numbers are 0-based internally, but all user-facing location
        strings must be 1-based for consistency with every other tool output.
        """
        file1 = _make_symbol("transport", kind=SymbolKind.File)
        send1 = _make_symbol("send", kind=SymbolKind.Function, parent=file1,
                             location={"relativePath": "src/transport.ts",
                                        "range": {"start": {"line": 41, "character": 0},
                                                  "end": {"line": 46, "character": 0}}})
        file1["children"] = [send1]

        file2 = _make_symbol("main", kind=SymbolKind.File)
        send2 = _make_symbol("send", kind=SymbolKind.Function, parent=file2,
                             location={"relativePath": "src/main.ts",
                                        "range": {"start": {"line": 131, "character": 0},
                                                  "end": {"line": 175, "character": 0}}})
        file2["children"] = [send2]

        tree = [file1, file2]
        ls = self._make_ls_mock(tree)
        with pytest.raises(SymbolResolutionError) as exc_info:
            resolve_unique_symbol(ls, "send")  # type: ignore[arg-type]

        candidates = exc_info.value.candidates
        assert len(candidates) == 2

        # The location strings should use 1-based line numbers (raw + 1)
        locs = [c["location"] for c in candidates]
        # src/transport.ts raw lines 41-46 → 1-based should be 42-47
        assert "src/transport.ts:42-47" in locs, \
            f"Expected 1-based 42-47 in candidates, got: {locs}"
        # src/main.ts raw lines 131-175 → 1-based should be 132-176
        assert "src/main.ts:132-176" in locs, \
            f"Expected 1-based 132-176 in candidates, got: {locs}"

    # -- zero matches --

    def test_zero_matches_raises_error(self):
        tree = self._tree()
        ls = self._make_ls_mock(tree)
        with pytest.raises(SymbolResolutionError) as exc_info:
            resolve_unique_symbol(ls, "nonexistent")  # type: ignore[arg-type]
        assert "No symbol matches" in str(exc_info.value)

    # -- overload indices in resolution --

    def test_overload_index_in_resolution(self):
        """Overloaded methods should be distinguishable."""
        klass = _make_symbol("Foo", kind=SymbolKind.Class)
        method0 = _make_symbol("bar", overload_idx=0, parent=klass,
                               location={"relativePath": "src/foo.ts",
                                          "range": {"start": {"line": 5, "character": 0},
                                                    "end": {"line": 10, "character": 0}}})
        method1 = _make_symbol("bar", overload_idx=1, parent=klass,
                               location={"relativePath": "src/foo.ts",
                                          "range": {"start": {"line": 15, "character": 0},
                                                    "end": {"line": 20, "character": 0}}})
        klass["children"] = [method0, method1]
        file = _make_symbol("foo", kind=SymbolKind.File, children=[klass])
        ls = self._make_ls_mock([file])

        result = resolve_unique_symbol(ls, "Foo/bar[0]")  # type: ignore[arg-type]
        assert result["overload_idx"] == 0

        result2 = resolve_unique_symbol(ls, "Foo/bar[1]")  # type: ignore[arg-type]
        assert result2["overload_idx"] == 1

    # -- relative_path scoping --

    def test_relative_path_passed_to_ls(self):
        """Verify that relative_path is forwarded to request_full_symbol_tree."""
        tree = self._tree()
        received_paths = []

        class MockLS:
            def request_full_symbol_tree(self, within_relative_path=None):
                received_paths.append(within_relative_path)
                return tree

        ls = MockLS()
        resolve_unique_symbol(ls, "shutdown", relative_path="src/")  # type: ignore[arg-type]
        assert received_paths == ["src/"]


# ---------------------------------------------------------------------------
# resolve_unique_symbol_via_workspace
# ---------------------------------------------------------------------------


class TestResolveUniqueSymbolViaWorkspace:
    """Test resolve_unique_symbol_via_workspace with mocked LS methods.

    Verifies that the function falls back to resolve_unique_symbol when
    workspace/symbol returns an empty list (the Bug 1 scenario), not just
    when it returns None or raises.
    """

    def test_falls_back_on_empty_workspace_symbol(self):
        """When workspace/symbol returns [], fall back to full tree."""
        # Build a minimal full tree: a nested arrow-like function 'execute'
        # inside a 'config' object — the kind of symbol that workspace/symbol
        # might not index but the full document symbol tree has.
        file1 = _make_symbol("config", kind=SymbolKind.File)
        config_var = _make_symbol(
            "config",
            kind=SymbolKind.Variable,
            parent=file1,
            children=[
                _make_symbol(
                    "execute",
                    kind=SymbolKind.Function,
                    location={
                        "relativePath": "src/config.ts",
                        "range": {
                            "start": {"line": 2, "character": 0},
                            "end": {"line": 4, "character": 0},
                        },
                    },
                )
            ],
        )
        file1["children"] = [config_var]
        tree = [file1]

        full_tree_called = [False]

        class MockLS:
            @staticmethod
            def request_workspace_symbol(query):
                return []  # Empty — the Bug 1 trigger

            @staticmethod
            def request_full_symbol_tree(within_relative_path=None):
                full_tree_called[0] = True
                return tree

        ls = MockLS()
        result = resolve_unique_symbol_via_workspace(
            [ls], "execute", relative_path=None  # type: ignore[arg-type]
        )
        assert result["name"] == "execute"
        assert result["kind"] == SymbolKind.Function
        assert full_tree_called[0], "Full tree fallback should have been called when workspace/symbol returned []"

    def test_still_works_when_workspace_symbol_returns_none(self):
        """When workspace/symbol returns None (unsupported), fall back to full tree."""
        file1 = _make_symbol("mod", kind=SymbolKind.File)
        fn = _make_symbol(
            "helper",
            kind=SymbolKind.Function,
            parent=file1,
            location={
                "relativePath": "src/mod.ts",
                "range": {
                    "start": {"line": 1, "character": 0},
                    "end": {"line": 3, "character": 0},
                },
            },
        )
        file1["children"] = [fn]
        tree = [file1]

        full_tree_called = [False]

        class MockLS:
            @staticmethod
            def request_workspace_symbol(query):
                return None  # Unsupported

            @staticmethod
            def request_full_symbol_tree(within_relative_path=None):
                full_tree_called[0] = True
                return tree

        ls = MockLS()
        result = resolve_unique_symbol_via_workspace(
            [ls], "helper", relative_path=None  # type: ignore[arg-type]
        )
        assert result["name"] == "helper"
        assert full_tree_called[0], "Full tree fallback should have been called when workspace/symbol returned None"

    def test_raises_when_no_match_in_either(self):
        """When neither workspace/symbol nor full tree find the symbol, raise error."""
        empty_tree: list[UnifiedSymbolInformation] = []

        class MockLS:
            @staticmethod
            def request_workspace_symbol(query):
                return []

            @staticmethod
            def request_full_symbol_tree(within_relative_path=None):
                return empty_tree

        ls = MockLS()
        with pytest.raises(SymbolResolutionError) as exc_info:
            resolve_unique_symbol_via_workspace(
                [ls], "nonexistent", relative_path=None  # type: ignore[arg-type]
            )
        assert "No symbol matches" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
