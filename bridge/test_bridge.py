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

from serena_pi_bridge import Bridge


# ---------------------------------------------------------------------------
# _ls_list_for — directory-aware LS dispatch (Bug 2)
# ---------------------------------------------------------------------------

class TestLsListFor:
    """Test that _ls_list_for returns all LS instances when relative_path is a
    directory, and a single instance when it is a file.

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
    def bridge_with_ls_map(self, tmp_path: Path) -> Bridge:
        """Create a Bridge with _ls_map populated but no real LS started."""
        bridge = Bridge()
        bridge.cwd = str(tmp_path)
        bridge.language = "typescript"
        bridge._ls_map = {
            "typescript": self._make_mock_ls(),
            "python": self._make_mock_ls(),
        }
        bridge._languages = ["typescript", "python"]
        return bridge

    def test_directory_returns_all_ls_instances(self, bridge_with_ls_map: Bridge):
        """When relative_path is a directory, return all LS instances."""
        # Create a real subdirectory in the tmp project root
        sub_dir = Path(bridge_with_ls_map.cwd) / "mysubdir"  # type: ignore[arg-type]
        sub_dir.mkdir()

        result = bridge_with_ls_map._ls_list_for("mysubdir")
        ls_langs = set()
        for ls in result:
            for lang, stored_ls in bridge_with_ls_map._ls_map.items():
                if ls is stored_ls:
                    ls_langs.add(lang)
        assert ls_langs == {"typescript", "python"}, (
            f"Expected both LS instances for directory, got languages: {ls_langs}"
        )

    def test_file_returns_single_ls_instance(self, bridge_with_ls_map: Bridge):
        """When relative_path is a file, return the LS for its extension."""
        # Create a real .ts file
        ts_file = Path(bridge_with_ls_map.cwd) / "index.ts"  # type: ignore[arg-type]
        ts_file.touch()

        result = bridge_with_ls_map._ls_list_for("index.ts")
        assert len(result) == 1, f"Expected single LS for file, got {len(result)}"
        assert result[0] is bridge_with_ls_map._ls_map["typescript"], (
            "File should use TypeScript LS"
        )

    def test_nonexistent_path_falls_back_to_extension_dispatch(
        self, bridge_with_ls_map: Bridge
    ):
        """When relative_path doesn't exist on disk, use extension-based dispatch."""
        result = bridge_with_ls_map._ls_list_for("nonexistent.py")
        assert len(result) == 1, f"Expected single LS for .py file, got {len(result)}"
        assert result[0] is bridge_with_ls_map._ls_map["python"], (
            "Nonexistent .py file should dispatch to Python LS"
        )

    def test_project_wide_returns_all_ls_instances(self, bridge_with_ls_map: Bridge):
        """When relative_path is None, return all LS instances."""
        result = bridge_with_ls_map._ls_list_for(None)
        assert len(result) == 2, f"Expected 2 LS instances for project-wide, got {len(result)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
