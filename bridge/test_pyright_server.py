"""Unit tests for PyrightServer — specifically is_ignored_dirname (Issue #26).

is_ignored_dirname is a pure method that only accesses class-level
constants (_ALWAYS_IGNORED_DIRS and the subclass-specific list).
We can test it without constructing a full PyrightServer (which would
needlessly create a LanguageServerProcess, caches, and pathspec).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure bridge/ is importable.
_BRIDGE_DIR = Path(__file__).resolve().parent
if str(_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_DIR))

import pytest

from solidlsp.language_servers.pyright_server import PyrightServer


@pytest.fixture
def pyright_server() -> PyrightServer:
    """Construct a PyrightServer without heavy init — is_ignored_dirname is pure."""
    return object.__new__(PyrightServer)


class TestIsIgnoredDirname:
    """Issue #26: PyrightServer must exclude node_modules directories."""

    def test_node_modules_is_ignored(self, pyright_server):
        """Directory named 'node_modules' must be ignored."""
        assert pyright_server.is_ignored_dirname("node_modules") is True, (
            "node_modules should be ignored to prevent polluting find_symbol "
            "results with vendored Pyright type stubs"
        )

    def test_existing_ignored_dirnames_still_work(self, pyright_server):
        """Existing exclusions must not regress."""
        assert pyright_server.is_ignored_dirname("venv") is True
        assert pyright_server.is_ignored_dirname("__pycache__") is True

    def test_normal_dirnames_are_not_ignored(self, pyright_server):
        """Normal project directories must not be flagged as ignored."""
        assert pyright_server.is_ignored_dirname("src") is False
        assert pyright_server.is_ignored_dirname("bridge") is False
        assert pyright_server.is_ignored_dirname("tests") is False

    def test_dot_prefixes_still_ignored_via_base_class(self, pyright_server):
        """Dot-prefixed directories from the base class must remain ignored."""
        assert pyright_server.is_ignored_dirname(".git") is True
        assert pyright_server.is_ignored_dirname(".venv") is True
        assert pyright_server.is_ignored_dirname(".cache") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
