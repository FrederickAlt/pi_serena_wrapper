"""Tests for path_validation.validate_project_path."""

from __future__ import annotations

import os
import tempfile

import pytest

from path_validation import validate_project_path


class TestValidateProjectPath:
    """Path containment and traversal rejection."""

    @pytest.fixture
    def tmp_project(self) -> str:
        with tempfile.TemporaryDirectory() as d:
            # Create a real file to test legitimate access
            open(os.path.join(d, "real.py"), "w").close()
            yield d

    def test_relative_path_within_project(self, tmp_project: str) -> None:
        result = validate_project_path("real.py", tmp_project)
        assert result.is_file()
        assert str(result).startswith(tmp_project)

    def test_absolute_path_bypass(self, tmp_project: str) -> None:
        with pytest.raises(ValueError, match="Path must be within the project root"):
            validate_project_path("/etc/passwd", tmp_project)

    def test_dotdot_traversal(self, tmp_project: str) -> None:
        with tempfile.TemporaryDirectory() as sibling:
            sibling_file = os.path.join(sibling, "secret.txt")
            with open(sibling_file, "w") as f:
                f.write("secret")
            rel = os.path.join("..", os.path.basename(sibling), "secret.txt")
            with pytest.raises(ValueError, match="Path must be within the project root"):
                validate_project_path(rel, tmp_project)

    def test_symlink_escape(self, tmp_project: str) -> None:
        with tempfile.TemporaryDirectory() as outside:
            outside_file = os.path.join(outside, "secret.txt")
            with open(outside_file, "w") as f:
                f.write("secret")
            link = os.path.join(tmp_project, "escape_link")
            os.symlink(outside_file, link)
            with pytest.raises(ValueError, match="Path must be within the project root"):
                validate_project_path("escape_link", tmp_project)

    def test_empty_path_returns_root(self, tmp_project: str) -> None:
        result = validate_project_path("", tmp_project)
        assert result.is_dir()
        assert str(result) == tmp_project

    def test_dot_path_returns_root(self, tmp_project: str) -> None:
        result = validate_project_path(".", tmp_project)
        assert result.is_dir()
        assert str(result) == tmp_project
