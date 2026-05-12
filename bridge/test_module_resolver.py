"""Unit tests for bridge/module_resolver.py — no LSP needed."""

from __future__ import annotations

import sys
from pathlib import Path

_BRIDGE_DIR = Path(__file__).resolve().parent
if str(_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_DIR))

import pytest

from module_resolver import ModuleResolver


# ---------------------------------------------------------------------------
# Python resolver — non-relative bare imports
# ---------------------------------------------------------------------------

class TestPythonResolverBareImport:
    """Non-relative imports from nested directories should walk up the
    directory hierarchy and generate candidate paths at each level,
    plus the project root."""

    def test_bare_import_from_nested_dir(self):
        """``formatting`` imported from ``bridge/tools/find_symbol.py``
        should include ``bridge/formatting.py`` as a candidate."""
        resolver = ModuleResolver.get("python")
        candidates = resolver("formatting", "bridge/tools/find_symbol.py")
        assert "bridge/formatting.py" in candidates
        assert "bridge/formatting/__init__.py" in candidates
        # Also includes same-dir and project-root candidates
        assert "bridge/tools/formatting.py" in candidates
        assert "formatting.py" in candidates

    def test_bare_import_from_file_in_project_root(self):
        """``formatting`` imported from a file at the project root
        should have only root-level candidates."""
        resolver = ModuleResolver.get("python")
        candidates = resolver("formatting", "serena_pi_bridge.py")
        assert candidates == [
            "formatting.py",
            "formatting/__init__.py",
        ]

    def test_bare_import_from_shallow_dir(self):
        """``utils`` imported from ``src/main.py`` should produce
        ``src/utils.py`` and ``utils.py`` candidates."""
        resolver = ModuleResolver.get("python")
        candidates = resolver("utils", "src/main.py")
        assert "src/utils.py" in candidates
        assert "utils.py" in candidates


# ---------------------------------------------------------------------------
# Python resolver — dotted imports
# ---------------------------------------------------------------------------

class TestPythonResolverDottedImport:
    """Dotted imports like ``solidlsp.ls_config`` should convert dots
    to path separators before generating candidates."""

    def test_dotted_import_from_nested_dir(self):
        """``solidlsp.ls_config`` from ``bridge/tools/find_symbol.py``
        should include ``bridge/solidlsp/ls_config.py``."""
        resolver = ModuleResolver.get("python")
        candidates = resolver("solidlsp.ls_config", "bridge/tools/find_symbol.py")
        assert "bridge/solidlsp/ls_config.py" in candidates
        assert "bridge/solidlsp/ls_config/__init__.py" in candidates
        assert "bridge/tools/solidlsp/ls_config.py" in candidates
        assert "solidlsp/ls_config.py" in candidates

    def test_deeply_dotted_from_root(self):
        """``a.b.c`` from ``main.py`` should give ``a/b/c.py`` etc."""
        resolver = ModuleResolver.get("python")
        candidates = resolver("a.b.c", "main.py")
        assert "a/b/c.py" in candidates
        assert "a/b/c/__init__.py" in candidates
        # Root-level file → only root-level candidates
        assert len(candidates) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
