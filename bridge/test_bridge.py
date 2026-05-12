"""Unit tests for Bridge helpers — directory-aware _ls_list_for, etc."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import cast

_BRIDGE_DIR = Path(__file__).resolve().parent
if str(_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_DIR))

import pytest

from language_server_manager import LanguageServerManager


# ---------------------------------------------------------------------------
# _ls_list_for — directory-aware LS dispatch (Bug 2)
# ---------------------------------------------------------------------------

class TestLsListFor:
    """Test directory-aware language-server dispatch.

    Uses a temporary directory as the project root to simulate file-system
    checks without starting real language servers.
    """

    @staticmethod
    def _make_mock_ls():
        """Create a minimal mock language server with a repository_root_path."""
        class MockLS:
            repository_root_path = "/fake/root"

        return MockLS()

    @pytest.fixture
    def manager_with_ls_map(self, tmp_path: Path) -> LanguageServerManager:
        """Create a manager with fake language servers, no real LS startup."""
        manager = LanguageServerManager()
        manager.cwd = str(tmp_path)
        manager._primary_language = "typescript"
        ts_ls = self._make_mock_ls()
        manager._ls_map = {
            "typescript": ts_ls,  # type: ignore[dict-item]
            "python": self._make_mock_ls(),
        }
        manager._languages = ["typescript", "python"]
        return manager

    def test_directory_returns_all_ls_instances(self, manager_with_ls_map: LanguageServerManager):
        """When relative_path is a directory, return all LS instances."""
        sub_dir = Path(manager_with_ls_map.cwd) / "mysubdir"  # type: ignore[arg-type]
        sub_dir.mkdir()

        result = manager_with_ls_map.ls_list_for("mysubdir")
        ls_langs = set()
        for ls in result:
            for lang, stored_ls in manager_with_ls_map.ls_map.items():
                if ls is stored_ls:
                    ls_langs.add(lang)
        assert ls_langs == {"typescript", "python"}, (
            f"Expected both LS instances for directory, got languages: {ls_langs}"
        )

    def test_file_returns_single_ls_instance(self, manager_with_ls_map: LanguageServerManager):
        """When relative_path is a file, return the LS for its extension."""
        ts_file = Path(manager_with_ls_map.cwd) / "index.ts"  # type: ignore[arg-type]
        ts_file.touch()

        result = manager_with_ls_map.ls_list_for("index.ts")
        assert len(result) == 1, f"Expected single LS for file, got {len(result)}"
        assert result[0] is manager_with_ls_map.ls_map["typescript"], (
            "File should use TypeScript LS"
        )

    def test_nonexistent_path_falls_back_to_extension_dispatch(
        self, manager_with_ls_map: LanguageServerManager
    ):
        """When relative_path doesn't exist on disk, use extension-based dispatch."""
        result = manager_with_ls_map.ls_list_for("nonexistent.py")
        assert len(result) == 1, f"Expected single LS for .py file, got {len(result)}"
        assert result[0] is manager_with_ls_map.ls_map["python"], (
            "Nonexistent .py file should dispatch to Python LS"
        )

    def test_project_wide_returns_all_ls_instances(self, manager_with_ls_map: LanguageServerManager):
        """When relative_path is None, return all LS instances."""
        result = manager_with_ls_map.ls_list_for(None)
        assert len(result) == 2, f"Expected 2 LS instances for project-wide, got {len(result)}"

    def test_unknown_extension_falls_back_to_primary(
        self, manager_with_ls_map: LanguageServerManager
    ):
        """A path with an unrecognised extension dispatches to the primary LS."""
        result = manager_with_ls_map.ls_list_for("script.foo")
        assert len(result) == 1, f"Expected single LS for unknown ext, got {len(result)}"
        assert result[0] is manager_with_ls_map.ls_map["typescript"], (
            "Unknown extension should fall back to primary (typescript)"
        )

    def test_no_extension_falls_back_to_primary(
        self, manager_with_ls_map: LanguageServerManager
    ):
        """A path without any extension dispatches to the primary LS."""
        result = manager_with_ls_map.ls_list_for("Makefile")
        assert len(result) == 1, f"Expected single LS for no-ext path, got {len(result)}"
        assert result[0] is manager_with_ls_map.ls_map["typescript"], (
            "No-extension path should fall back to primary (typescript)"
        )

    def test_empty_string_is_directory_returns_all(
        self, manager_with_ls_map: LanguageServerManager
    ):
        """Empty string resolves to the project root (a directory) → all LS."""
        result = manager_with_ls_map.ls_list_for("")
        ls_langs = set()
        for ls in result:
            for lang, stored_ls in manager_with_ls_map.ls_map.items():
                if ls is stored_ls:
                    ls_langs.add(lang)
        assert ls_langs == {"typescript", "python"}, (
            f"Empty string should resolve to project root dir, got languages: {ls_langs}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
