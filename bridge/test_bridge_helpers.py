"""Unit tests for Bridge static/pure helper functions.

These functions have no side effects and do not require a language server
or filesystem — they are pure data transformations.  Fast feedback during
development; complement the expensive JSONL regression test.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

_BRIDGE_DIR = Path(__file__).resolve().parent
if str(_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_DIR))

import pytest

from solidlsp.ls_types import UnifiedSymbolInformation, SymbolKind
from serena_pi_bridge import Bridge
from import_resolver import _resolve_python_module, _verify_module_file_match
import formatting


# ---------------------------------------------------------------------------
# Helpers — hand-crafted symbol trees
# ---------------------------------------------------------------------------

def _make_symbol(
    name: str,
    kind: int = SymbolKind.Method,
    *,
    children: list[UnifiedSymbolInformation] | None = None,
    location: dict | None = None,
    range_dict: dict | None = None,
) -> UnifiedSymbolInformation:
    """Build a minimal UnifiedSymbolInformation for testing.

    *location* sets the nested location dict (full symbol tree shape).
    *range_dict* sets a top-level "range" key (document symbol shape).
    """
    sym: UnifiedSymbolInformation = cast(UnifiedSymbolInformation, {
        "name": name,
        "kind": kind,
        "children": children or [],
    })
    if location is not None:
        sym["location"] = location
    if range_dict is not None:
        sym["range"] = range_dict
    return sym


def _with_range(start_line: int, end_line: int) -> dict:
    """Create a minimal LSP range dict (0-based lines)."""
    return {
        "start": {"line": start_line, "character": 0},
        "end": {"line": end_line, "character": 0},
    }


def _with_location(relative_path: str, start_line: int, end_line: int) -> dict:
    """Create a minimal LSP location dict."""
    return {
        "relativePath": relative_path,
        "range": _with_range(start_line, end_line),
    }


# ---------------------------------------------------------------------------
# _extract_hover_text
# ---------------------------------------------------------------------------

class TestExtractHoverText:
    """Test _extract_hover_text — no LSP dependency, pure string extraction.

    The LSP Hover response has several shapes depending on the language
    server.  This function normalizes them all to plain text.
    """

    def test_none_returns_empty(self):
        assert formatting.extract_hover_text(None) == ""

    def test_non_dict_returns_empty(self):
        assert formatting.extract_hover_text([]) == ""
        assert formatting.extract_hover_text(42) == ""

    def test_no_contents_returns_empty(self):
        assert formatting.extract_hover_text({}) == ""

    def test_contents_is_none_returns_empty(self):
        assert formatting.extract_hover_text({"contents": None}) == ""

    def test_contents_is_plain_string(self):
        result = formatting.extract_hover_text({"contents": "Hello, world!"})
        assert result == "Hello, world!"

    def test_contents_is_markup_content_dict(self):
        # MarkupContent: {"kind": "markdown", "value": "**bold**"}
        result = formatting.extract_hover_text({
            "contents": {"kind": "markdown", "value": "**bold**"}
        })
        assert result == "**bold**"

    def test_contents_is_markup_content_without_value(self):
        result = formatting.extract_hover_text({
            "contents": {"kind": "plaintext"}
        })
        assert result == ""

    def test_contents_is_marked_string(self):
        # MarkedString: {"language": "python", "value": "def foo()"}
        result = formatting.extract_hover_text({
            "contents": {"language": "python", "value": "def foo()"}
        })
        assert result == "def foo()"

    def test_contents_is_list_of_strings(self):
        result = formatting.extract_hover_text({
            "contents": ["line one", "line two"]
        })
        assert result == "line one\nline two"

    def test_contents_is_list_of_marked_strings(self):
        result = formatting.extract_hover_text({
            "contents": [
                {"language": "python", "value": "def foo()"},
                {"language": "python", "value": "def bar()"},
            ]
        })
        assert result == "def foo()\ndef bar()"

    def test_contents_is_mixed_list(self):
        result = formatting.extract_hover_text({
            "contents": [
                "plain string",
                {"language": "python", "value": "def foo()"},
            ]
        })
        assert result == "plain string\ndef foo()"

    def test_contents_list_with_items_lacking_value(self):
        result = formatting.extract_hover_text({
            "contents": [
                {"language": "python"},  # no 'value'
                {"value": "has value"},
            ]
        })
        assert result == "has value"


# ---------------------------------------------------------------------------
# _verify_module_file_match
# ---------------------------------------------------------------------------

class TestVerifyModuleFileMatch:
    """Test _verify_module_file_match — the import classification gate.

    This is a ~20-line function with 8 conditional branches that decides
    whether a resolved symbol location actually belongs to the imported
    module.  It handles single-file and multi-file location strings,
    normalizes extensions (py/pyi/ts/tsx/js/jsx/mjs/mts/cts/cjs), and
    matches against __init__/index patterns plus vendored sub-modules.
    """

    # -- single-file matches --

    def test_exact_stem_match(self):
        """Source file stem matches module path directly."""
        assert _verify_module_file_match(
            "src/foo.py:10-20", "foo"
        ) is True

    def test_dotted_module_match(self):
        """Module path 'src.foo' matches 'src/foo.py'."""
        assert _verify_module_file_match(
            "src/foo.py:10-20", "src.foo"
        ) is True

    def test_dotted_module_with_pyi(self):
        """Stub files (.pyi) treated same as .py."""
        assert _verify_module_file_match(
            "src/foo.pyi:10-20", "src.foo"
        ) is True

    def test_typescript_extension_stripped(self):
        """TypeScript extensions stripped for stem matching."""
        assert _verify_module_file_match(
            "lib/util.ts:5-10", "lib.util"
        ) is True

    def test_tsx_extension_stripped(self):
        assert _verify_module_file_match(
            "components/Button.tsx:20-30", "components.Button"
        ) is True

    def test_js_extension_stripped(self):
        assert _verify_module_file_match(
            "src/index.js:1-5", "src.index"
        ) is True

    def test_mjs_extension_stripped(self):
        assert _verify_module_file_match(
            "src/helper.mjs:1-5", "src.helper"
        ) is True

    def test_mts_extension_stripped(self):
        assert _verify_module_file_match(
            "src/tool.mts:1-5", "src.tool"
        ) is True

    def test_cts_cjs_extensions_stripped(self):
        assert _verify_module_file_match(
            "pkg/entry.cts:1-5", "pkg.entry"
        ) is True
        assert _verify_module_file_match(
            "pkg/entry.cjs:1-5", "pkg.entry"
        ) is True

    # -- __init__ matches --

    def test_init_py_match(self):
        """'__init__.py' in module directory means the directory is the module."""
        assert _verify_module_file_match(
            "src/mypkg/__init__.py:10-20", "src.mypkg"
        ) is True

    def test_init_py_match_with_trailing_slash_module(self):
        """Module path should also match __init__.py for the stem+init pattern."""
        assert _verify_module_file_match(
            "mypkg/__init__.py:10-20", "mypkg"
        ) is True

    # -- index matches (TypeScript) --

    def test_index_ts_match(self):
        """'index.ts' in a directory means the directory is the module."""
        assert _verify_module_file_match(
            "components/index.ts:1-10", "components"
        ) is True

    def test_dotted_index_match(self):
        assert _verify_module_file_match(
            "src/components/index.ts:1-10", "src.components"
        ) is True

    # -- vendored sub-modules --

    def test_vendored_submodule_match(self):
        """A vendored sub-package path contains the module as directory component."""
        assert _verify_module_file_match(
            "solidlsp/ls_config.py:1-10", "solidlsp.ls_config"
        ) is True

    def test_vendored_deep_submodule_match(self):
        assert _verify_module_file_match(
            "vendor/solidlsp/ls_config.py:1-10", "solidlsp.ls_config"
        ) is True

    # -- non-matches (the important ones — these prevent false positives) --

    def test_different_name_no_match(self):
        """A completely different file name does not match."""
        assert _verify_module_file_match(
            "src/bar.py:5-10", "foo"
        ) is False

    def test_partial_name_no_match(self):
        """'utils' is not a subpath of 'util'."""
        assert _verify_module_file_match(
            "src/utils.py:5-10", "src.util"
        ) is False

    def test_partial_module_no_match(self):
        """'utils.helpers' does not match 'utils.py' — the module is deeper."""
        assert _verify_module_file_match(
            "src/utils.py:5-10", "src.utils.helpers"
        ) is False

    def test_different_directory_no_match(self):
        """Correct file name but wrong directory."""
        assert _verify_module_file_match(
            "lib/foo.py:1-5", "src.foo"
        ) is False

    # -- multi-file locations (re-exports) --

    def test_multifile_any_match_single(self):
        """When names resolve to multiple files, any match is sufficient."""
        assert _verify_module_file_match(
            "src/a.py:1-5; src/b.py:10-15", "src.a"
        ) is True

    def test_multifile_any_match_second(self):
        """Match on second file in the list."""
        assert _verify_module_file_match(
            "src/a.py:1-5; src/b.py:10-15", "src.b"
        ) is True

    def test_multifile_neither_matches(self):
        """Neither resolved file matches the module."""
        assert _verify_module_file_match(
            "src/a.py:1-5; src/b.py:10-15", "src.c"
        ) is False

    def test_multifile_partial_before_colon(self):
        """Range part before colon is stripped correctly in multi-file parsing."""
        assert _verify_module_file_match(
            "src/x.py:1-5; lib/y.ts:10-15", "lib.y"
        ) is True

    # -- edge cases --

    def test_empty_location(self):
        assert _verify_module_file_match("", "foo") is False

    def test_location_no_colon(self):
        """Single-file location without range part."""
        assert _verify_module_file_match(
            "src/foo.py", "src.foo"
        ) is True

    def test_windows_path_separator_normalized(self):
        """Backslash paths are normalized."""
        assert _verify_module_file_match(
            r"src\foo.py:10-20", "src.foo"
        ) is True


# ---------------------------------------------------------------------------
# _format_overview_symbols
# ---------------------------------------------------------------------------

class TestFormatOverviewSymbols:
    """Test _format_overview_symbols — recursive symbol formatting with
    depth control and kind filtering."""

    def test_empty_list(self):
        assert formatting.format_overview_symbols([], 0, 0) == ""

    # _format_overview_symbols reads range at the top level of the symbol
    # (document symbol shape), not nested inside location.

    def test_single_symbol_no_filter(self):
        sym = _make_symbol("MyClass", kind=SymbolKind.Class,
                           range_dict=_with_range(9, 25))
        result = formatting.format_overview_symbols([sym], 0, 0)
        assert result == "Class MyClass:10-26"

    def test_single_symbol_function(self):
        sym = _make_symbol("doWork", kind=SymbolKind.Function,
                           range_dict=_with_range(14, 20))
        result = formatting.format_overview_symbols([sym], 0, 0)
        assert result == "Function doWork:15-21"

    def test_indentation_by_depth(self):
        sym = _make_symbol("top", kind=SymbolKind.Class,
                           range_dict=_with_range(0, 10))
        # At depth 2, indent = 4 spaces
        result = formatting.format_overview_symbols([sym], 0, 2)
        assert result == "    Class top:1-11"

    def test_nested_with_max_depth_zero(self):
        """depth=0 means only top-level symbols."""
        child = _make_symbol("inner", kind=SymbolKind.Method,
                             range_dict=_with_range(5, 8))
        parent = _make_symbol("Outer", kind=SymbolKind.Class,
                              range_dict=_with_range(1, 15),
                              children=[child])
        result = formatting.format_overview_symbols([parent], 0, 0)
        assert result == "Class Outer:2-16"

    def test_nested_with_max_depth_one(self):
        """depth=1 means two levels."""
        child = _make_symbol("inner", kind=SymbolKind.Method,
                             range_dict=_with_range(5, 8))
        parent = _make_symbol("Outer", kind=SymbolKind.Class,
                              range_dict=_with_range(1, 15),
                              children=[child])
        result = formatting.format_overview_symbols([parent], 1, 0)
        expected = "Class Outer:2-16\n  Method inner:6-9"
        assert result == expected

    def test_nested_with_max_depth_two(self):
        """depth=2 → three levels."""
        grandchild = _make_symbol("deep", kind=SymbolKind.Function,
                                  range_dict=_with_range(7, 9))
        child = _make_symbol("inner", kind=SymbolKind.Method,
                             range_dict=_with_range(5, 10),
                             children=[grandchild])
        parent = _make_symbol("Outer", kind=SymbolKind.Class,
                              range_dict=_with_range(1, 20),
                              children=[child])
        result = formatting.format_overview_symbols([parent], 2, 0)
        expected = (
            "Class Outer:2-21\n"
            "  Method inner:6-11\n"
            "    Function deep:8-10"
        )
        assert result == expected

    def test_kind_filter_includes_only_specified(self):
        sym_class = _make_symbol("A", kind=SymbolKind.Class,
                                 range_dict=_with_range(1, 5))
        sym_func = _make_symbol("b", kind=SymbolKind.Function,
                                range_dict=_with_range(7, 10))

        result = formatting.format_overview_symbols(
            [sym_class, sym_func], 0, 0,
            included_kinds={SymbolKind.Class}
        )
        assert "Class A" in result
        assert "Function b" not in result

    def test_kind_filter_excludes_children_too(self):
        """When parent is excluded by kind filter, children are also excluded."""
        child = _make_symbol("inner", kind=SymbolKind.Function,
                             range_dict=_with_range(3, 5))
        parent = _make_symbol("outer", kind=SymbolKind.Variable,  # filtered out
                              range_dict=_with_range(1, 10),
                              children=[child])

        result = formatting.format_overview_symbols(
            [parent], 1, 0,
            included_kinds={SymbolKind.Class}
        )
        # Variable is filtered → neither parent nor child appears
        assert result == ""

    def test_kind_filter_none_shows_all(self):
        """When included_kinds is None, no filtering occurs."""
        sym = _make_symbol("x", kind=SymbolKind.Variable,
                           range_dict=_with_range(1, 2))
        result = formatting.format_overview_symbols([sym], 0, 0, included_kinds=None)
        assert result == "Variable x:2-3"

    def test_multiple_siblings(self):
        syms = [
            _make_symbol("A", kind=SymbolKind.Class,
                         range_dict=_with_range(1, 5)),
            _make_symbol("B", kind=SymbolKind.Interface,
                         range_dict=_with_range(7, 12)),
            _make_symbol("C", kind=SymbolKind.Enum,
                         range_dict=_with_range(14, 20)),
        ]
        result = formatting.format_overview_symbols(syms, 0, 0)
        expected = (
            "Class A:2-6\n"
            "Interface B:8-13\n"
            "Enum C:15-21"
        )
        assert result == expected


# ---------------------------------------------------------------------------
# _flatten_tree
# ---------------------------------------------------------------------------

class TestFlattenTree:
    """Test _flatten_tree — recursive pre-order iterator."""

    def test_empty_list_yields_nothing(self):
        result = list(formatting.flatten_tree([]))
        assert result == []

    def test_flat_list_yields_all(self):
        syms = [
            _make_symbol("A", kind=SymbolKind.Class),
            _make_symbol("B", kind=SymbolKind.Function),
        ]
        result = list(formatting.flatten_tree(syms))
        assert len(result) == 2
        assert result[0]["name"] == "A"
        assert result[1]["name"] == "B"

    def test_nested_pre_order(self):
        """Pre-order: parent before children."""
        child = _make_symbol("child", kind=SymbolKind.Method)
        parent = _make_symbol("parent", kind=SymbolKind.Class, children=[child])
        result = list(formatting.flatten_tree([parent]))
        assert [s["name"] for s in result] == ["parent", "child"]

    def test_deeply_nested(self):
        grandchild = _make_symbol("gc", kind=SymbolKind.Function)
        child = _make_symbol("c", kind=SymbolKind.Method, children=[grandchild])
        parent = _make_symbol("p", kind=SymbolKind.Class, children=[child])
        result = list(formatting.flatten_tree([parent]))
        assert [s["name"] for s in result] == ["p", "c", "gc"]

    def test_two_branches_alternate_correctly(self):
        """Pre-order with siblings: all children of first root before second."""
        c1 = _make_symbol("c1", kind=SymbolKind.Method)
        c2 = _make_symbol("c2", kind=SymbolKind.Method)
        root1 = _make_symbol("A", kind=SymbolKind.Class, children=[c1, c2])
        root2 = _make_symbol("B", kind=SymbolKind.Class)
        result = list(formatting.flatten_tree([root1, root2]))
        assert [s["name"] for s in result] == ["A", "c1", "c2", "B"]

    def test_symbol_without_children_key(self):
        sym = cast(UnifiedSymbolInformation, {"name": "solo", "kind": SymbolKind.Function})
        result = list(formatting.flatten_tree([sym]))
        assert len(result) == 1
        assert result[0]["name"] == "solo"

    def test_symbol_with_empty_children(self):
        sym = _make_symbol("leaf", kind=SymbolKind.Function, children=[])
        result = list(formatting.flatten_tree([sym]))
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _format_location
# ---------------------------------------------------------------------------

class TestFormatLocation:
    """Test _format_location — compact location formatting."""

    def test_full_location(self):
        sym = _make_symbol("foo", kind=SymbolKind.Function,
                           location=_with_location("src/bar.ts", 5, 12))
        assert formatting.format_location(sym) == "src/bar.ts:6-13"

    def test_no_location_key(self):
        sym = _make_symbol("foo", kind=SymbolKind.Function)
        assert formatting.format_location(sym) == "unknown:0-0"

    def test_location_is_none(self):
        sym = cast(UnifiedSymbolInformation, {
            "name": "foo", "kind": SymbolKind.Function, "location": None
        })
        assert formatting.format_location(sym) == "unknown:0-0"

    def test_location_missing_relative_path(self):
        """When location exists but has no relativePath, uses range with 'unknown'."""
        sym = cast(UnifiedSymbolInformation, {
            "name": "foo", "kind": SymbolKind.Function,
            "location": {"range": _with_range(5, 12)}
        })
        assert formatting.format_location(sym) == "unknown:6-13"

    def test_location_missing_range(self):
        sym = cast(UnifiedSymbolInformation, {
            "name": "foo", "kind": SymbolKind.Function,
            "location": {"relativePath": "a.ts"}
        })
        assert formatting.format_location(sym) == "a.ts:0-0"

    def test_line_numbers_start_at_one(self):
        """0-based LSP lines become 1-based in output."""
        sym = _make_symbol("foo", kind=SymbolKind.Function,
                           location=_with_location("x.ts", 0, 0))
        assert formatting.format_location(sym) == "x.ts:1-1"


# ---------------------------------------------------------------------------
# _filter_imported_symbols
# ---------------------------------------------------------------------------

class TestFilterImportedSymbols:
    """Test _filter_imported_symbols — recursive filtering with copying."""

    def test_empty_list(self):
        result = formatting.filter_imported_symbols([], {"foo"})
        assert result == []

    def test_top_level_filtered_out(self):
        sym = _make_symbol("React", kind=SymbolKind.Class)
        result = formatting.filter_imported_symbols([sym], {"React"})
        assert result == []

    def test_top_level_kept(self):
        sym = _make_symbol("MyComponent", kind=SymbolKind.Class)
        result = formatting.filter_imported_symbols([sym], {"React"})
        assert len(result) == 1
        assert result[0]["name"] == "MyComponent"

    def test_nested_filtered_child(self):
        """Parent kept, imported child removed."""
        child = _make_symbol("React", kind=SymbolKind.Class)
        parent = _make_symbol("MyComp", kind=SymbolKind.Class, children=[child])
        result = formatting.filter_imported_symbols([parent], {"React"})
        assert len(result) == 1
        assert result[0]["name"] == "MyComp"
        children = result[0].get("children", [])
        assert len(children) == 0

    def test_nested_kept_child(self):
        """Non-imported child stays."""
        child = _make_symbol("helper", kind=SymbolKind.Function)
        parent = _make_symbol("MyComp", kind=SymbolKind.Class, children=[child])
        result = formatting.filter_imported_symbols([parent], {"React"})
        assert len(result) == 1
        children = result[0].get("children", [])
        assert len(children) == 1
        assert children[0]["name"] == "helper"

    def test_multiple_imported_names(self):
        syms = [
            _make_symbol("A", kind=SymbolKind.Class),
            _make_symbol("B", kind=SymbolKind.Function),
            _make_symbol("C", kind=SymbolKind.Interface),
        ]
        result = formatting.filter_imported_symbols(syms, {"A", "C"})
        assert len(result) == 1
        assert result[0]["name"] == "B"

    def test_does_not_mutate_original(self):
        """The original symbol list should not be modified."""
        child = _make_symbol("imported", kind=SymbolKind.Class)
        original = _make_symbol("top", kind=SymbolKind.Class, children=[child])
        result = formatting.filter_imported_symbols([original], {"imported"})
        # Original still has its child
        assert len(original.get("children", [])) == 1
        # Result has the child filtered out
        assert len(result[0].get("children", [])) == 0

    def test_symbol_without_children_key(self):
        sym = cast(UnifiedSymbolInformation, {"name": "x", "kind": SymbolKind.Function})
        result = formatting.filter_imported_symbols([sym], set())
        assert len(result) == 1
        assert result[0]["name"] == "x"

    def test_deeply_nested_imported_grandchild(self):
        grandchild = _make_symbol("useState", kind=SymbolKind.Function)
        child = _make_symbol("hooks", kind=SymbolKind.Function, children=[grandchild])
        parent = _make_symbol("App", kind=SymbolKind.Class, children=[child])
        result = formatting.filter_imported_symbols([parent], {"useState"})
        # Parent kept, child kept (not imported), grandchild removed
        assert result[0]["name"] == "App"
        child_result = result[0].get("children", [])[0]
        assert child_result["name"] == "hooks"
        assert child_result.get("children", []) == []


# ---------------------------------------------------------------------------
# _parse_kinds
# ---------------------------------------------------------------------------

class TestParseKinds:
    """Test _parse_kinds — SymbolKind name/integer conversion."""

    def test_none_returns_none(self):
        assert formatting.parse_kinds(None) is None

    def test_string_names(self):
        result = formatting.parse_kinds(["Class", "Method", "Function"])
        assert result == {
            SymbolKind.Class.value,
            SymbolKind.Method.value,
            SymbolKind.Function.value,
        }

    def test_integers_pass_through(self):
        result = formatting.parse_kinds([5, 6, 12])
        assert result == {5, 6, 12}

    def test_mixed_strings_and_integers(self):
        result = formatting.parse_kinds(["Class", 6])
        assert SymbolKind.Class.value in result
        assert 6 in result

    def test_unknown_name_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown SymbolKind name"):
            formatting.parse_kinds(["NotAKind"])

    def test_empty_list(self):
        result = formatting.parse_kinds([])
        assert result == set()

    def test_duplicates_deduplicated(self):
        result = formatting.parse_kinds(["Class", "Class", 5])
        assert result == {SymbolKind.Class.value}


# ---------------------------------------------------------------------------
# _resolve_python_module
# ---------------------------------------------------------------------------

class TestResolvePythonModule:
    """Test _resolve_python_module — Python-style import path resolution."""

    def test_same_package_single_dot(self):
        """`.utils` from `src/foo` → `src/utils`."""
        assert _resolve_python_module("src/foo", ".utils") == "src/foo/utils"

    def test_same_package_single_dot_from_root(self):
        """`.utils` from project root → `utils`."""
        assert _resolve_python_module("", ".utils") == "utils"

    def test_parent_package_double_dot(self):
        """`..src.utils` from `app/sub` → `app/src/utils`."""
        assert _resolve_python_module("app/sub", "..src.utils") == "app/src/utils"

    def test_double_dot_from_root(self):
        """`..foo` from empty dir → `.` stays (can't go above root)."""
        result = _resolve_python_module("", "..foo")
        assert result.startswith(".") or result == "foo"

    def test_triple_dot_deep(self):
        """`...deep` from `a/b/c` → goes up two → `a` then `deep`."""
        assert _resolve_python_module("a/b/c", "...deep") == "a/deep"

    def test_single_dot_without_module(self):
        """`.` (bare module, empty after stripping) → same directory."""
        assert _resolve_python_module("src/pkg", ".") == "src/pkg"

    def test_double_dot_without_module(self):
        """`..` → parent directory."""
        assert _resolve_python_module("src/pkg", "..") == "src"

    def test_module_no_leading_dots(self):
        """Non-relative should pass through unchanged (not typically used)."""
        result = _resolve_python_module("src", "solidlsp.ls_config")
        assert "solidlsp/ls_config" in result

    def test_from_root_directory(self):
        """File in project root with relative import."""
        assert _resolve_python_module("", ".config") == "config"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
