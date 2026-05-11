"""Unit tests for bridge/import_parser.py — fixture-based, no LSP needed."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure bridge/ is importable.
_BRIDGE_DIR = Path(__file__).resolve().parent
if str(_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_DIR))

import pytest

from import_parser import parse_imports, parse_imports_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise(pairs: list[tuple[str, str]]) -> set[tuple[str, str]]:
    """Convert to a set for order-independent comparison."""
    return set(pairs)


# ---------------------------------------------------------------------------
# Python — import X
# ---------------------------------------------------------------------------

class TestPythonImportX:
    def test_single_import(self):
        src = "import os\n"
        assert _normalise(parse_imports(src, "python")) == {("os", "os")}

    def test_multiple_imports_comma(self):
        src = "import os, sys, json\n"
        assert _normalise(parse_imports(src, "python")) == {
            ("os", "os"),
            ("sys", "sys"),
            ("json", "json"),
        }

    def test_dotted_import(self):
        src = "import os.path\n"
        assert _normalise(parse_imports(src, "python")) == {("os.path", "os.path")}

    def test_import_with_alias(self):
        src = "import numpy as np\n"
        assert _normalise(parse_imports(src, "python")) == {("np", "np")}


# ---------------------------------------------------------------------------
# Python — from X import Y
# ---------------------------------------------------------------------------

class TestPythonFromImport:
    def test_single_name(self):
        src = "from pathlib import Path\n"
        assert _normalise(parse_imports(src, "python")) == {("Path", "pathlib")}

    def test_multiple_names(self):
        src = "from typing import List, Dict, Optional\n"
        assert _normalise(parse_imports(src, "python")) == {
            ("List", "typing"),
            ("Dict", "typing"),
            ("Optional", "typing"),
        }

    def test_multi_line_parens(self):
        src = """from django.db import (
    models,
    fields,
)
"""
        assert _normalise(parse_imports(src, "python")) == {
            ("models", "django.db"),
            ("fields", "django.db"),
        }

    def test_alias(self):
        src = "from collections import OrderedDict as OD\n"
        assert _normalise(parse_imports(src, "python")) == {("OD", "collections")}


# ---------------------------------------------------------------------------
# Python — relative imports
# ---------------------------------------------------------------------------

class TestPythonRelativeImports:
    def test_single_dot(self):
        src = "from .utils import helper\n"
        assert _normalise(parse_imports(src, "python")) == {("helper", ".utils")}

    def test_double_dot(self):
        src = "from ..base import Base\n"
        assert _normalise(parse_imports(src, "python")) == {("Base", "..base")}

    def test_triple_dot(self):
        src = "from ...grandparent import Thing\n"
        assert _normalise(parse_imports(src, "python")) == {("Thing", "...grandparent")}

    def test_relative_with_alias(self):
        src = "from .sibling import func as f\n"
        assert _normalise(parse_imports(src, "python")) == {("f", ".sibling")}


# ---------------------------------------------------------------------------
# TypeScript — default imports
# ---------------------------------------------------------------------------

class TestTSDefaultImport:
    def test_single_default(self):
        src = 'import React from "react";\n'
        assert _normalise(parse_imports(src, "typescript")) == {("React", "react")}

    def test_single_default_tsx(self):
        src = 'import React from "react";\n'
        assert _normalise(parse_imports(src, "tsx")) == {("React", "react")}


# ---------------------------------------------------------------------------
# TypeScript — named imports
# ---------------------------------------------------------------------------

class TestTSNamedImports:
    def test_single_named(self):
        src = 'import { useState } from "react";\n'
        assert _normalise(parse_imports(src, "typescript")) == {("useState", "react")}

    def test_multiple_named(self):
        src = 'import { a, b, c } from "module";\n'
        assert _normalise(parse_imports(src, "typescript")) == {
            ("a", "module"),
            ("b", "module"),
            ("c", "module"),
        }


# ---------------------------------------------------------------------------
# TypeScript — namespace imports
# ---------------------------------------------------------------------------

class TestTSNamespaceImport:
    def test_namespace(self):
        src = 'import * as Everything from "module";\n'
        assert _normalise(parse_imports(src, "typescript")) == {("Everything", "module")}


# ---------------------------------------------------------------------------
# TypeScript — type-only imports
# ---------------------------------------------------------------------------

class TestTSTypeOnlyImports:
    def test_type_only_import(self):
        src = 'import type { User } from "./types";\n'
        assert _normalise(parse_imports(src, "typescript")) == {("User", "./types")}

    def test_inline_type_import(self):
        src = 'import { type Foo } from "./types";\n'
        assert _normalise(parse_imports(src, "typescript")) == {("Foo", "./types")}

    def test_type_only_default(self):
        src = 'import type MyType from "./types";\n'
        assert _normalise(parse_imports(src, "typescript")) == {("MyType", "./types")}


# ---------------------------------------------------------------------------
# TypeScript — combined default + named
# ---------------------------------------------------------------------------

class TestTSCombinedImport:
    def test_combined(self):
        src = 'import React, { useState, useEffect } from "react";\n'
        assert _normalise(parse_imports(src, "typescript")) == {
            ("React", "react"),
            ("useState", "react"),
            ("useEffect", "react"),
        }


# ---------------------------------------------------------------------------
# TypeScript — re-exports
# ---------------------------------------------------------------------------

class TestTSReexports:
    def test_simple_reexport(self):
        src = 'export { Foo } from "./module";\n'
        assert _normalise(parse_imports(src, "typescript")) == {("Foo", "./module")}

    def test_reexport_with_alias(self):
        src = 'export { Foo as Bar } from "./module";\n'
        assert _normalise(parse_imports(src, "typescript")) == {("Bar", "./module")}

    def test_multiple_reexports(self):
        src = 'export { X, Y } from "./module";\n'
        assert _normalise(parse_imports(src, "typescript")) == {
            ("X", "./module"),
            ("Y", "./module"),
        }


# ---------------------------------------------------------------------------
# TypeScript — require() calls
# ---------------------------------------------------------------------------

class TestTSRequire:
    def test_const_require(self):
        src = 'const path = require("path");\n'
        assert _normalise(parse_imports(src, "typescript")) == {("path", "path")}

    def test_require_without_const(self):
        src = 'require("side-effect");\n'
        assert _normalise(parse_imports(src, "typescript")) == {("side-effect", "side-effect")}


# ---------------------------------------------------------------------------
# TypeScript — dynamic import() expressions
# ---------------------------------------------------------------------------

class TestTSDynamicImport:
    def test_await_import(self):
        src = 'const mod = await import("./module");\n'
        assert _normalise(parse_imports(src, "typescript")) == {("./module", "./module")}

    def test_promise_import(self):
        src = 'import("./module").then(m => m.doThing());\n'
        assert _normalise(parse_imports(src, "typescript")) == {("./module", "./module")}


# ---------------------------------------------------------------------------
# Unknown language
# ---------------------------------------------------------------------------

class TestUnknownLanguage:
    def test_unknown_returns_empty(self):
        assert parse_imports("import foo", "ruby") == []
        assert parse_imports("import foo", "") == []
        assert parse_imports("import foo", "go") == []

    def test_case_insensitive(self):
        # Python/PYTHON should both work
        src = "import os\n"
        assert _normalise(parse_imports(src, "PYTHON")) == {("os", "os")}
        assert _normalise(parse_imports(src, "TYPESCRIPT")) == set()  # invalid TS but shouldn't crash


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_source(self):
        assert parse_imports("", "python") == []
        assert parse_imports("", "typescript") == []

    def test_no_imports_python(self):
        src = "x = 1\ndef foo():\n    pass\n"
        assert parse_imports(src, "python") == []

    def test_no_imports_typescript(self):
        src = "const x = 1;\nfunction foo() {}\n"
        assert parse_imports(src, "typescript") == []

    def test_single_quotes_typescript(self):
        src = "import X from './module';\n"
        assert _normalise(parse_imports(src, "typescript")) == {("X", "./module")}

    def test_backtick_string_typescript(self):
        src = "import X from `./module`;\n"
        # template strings are unusual but let's make sure we handle them
        pairs = parse_imports(src, "typescript")
        # The template might not be a simple 'string' node in TS; accept empty
        assert pairs == [] or pairs == [("./module", "./module")]


# ---------------------------------------------------------------------------
# parse_imports_file
# ---------------------------------------------------------------------------

class TestParseImportsFile:
    def test_file_reading(self, tmp_path: Path):
        file_path = tmp_path / "test.py"
        file_path.write_text("import os\nfrom pathlib import Path\n")
        result = parse_imports_file(str(file_path), "python")
        assert _normalise(result) == {("os", "os"), ("Path", "pathlib")}

    def test_tsx_file_reading(self, tmp_path: Path):
        file_path = tmp_path / "test.tsx"
        file_path.write_text('import React from "react";\n')
        result = parse_imports_file(str(file_path), "tsx")
        assert _normalise(result) == {("React", "react")}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
