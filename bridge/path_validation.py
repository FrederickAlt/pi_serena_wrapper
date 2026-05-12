"""Project-root path validation.

Ensures relative_path arguments passed to tools resolve to paths
within the project root, preventing directory traversal attacks.
"""

from __future__ import annotations

from pathlib import Path


def validate_project_path(relative_path: str, project_root: str) -> Path:
    """Resolve *relative_path* against *project_root* and verify containment.

    Returns the resolved, absolute ``Path``.  Raises ``ValueError`` if the
    resolved path escapes the project root — whether via absolute-path
    bypass, ``..`` traversal, or symlink escape.
    """
    root = Path(project_root).resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(
            f"Path must be within the project root: {relative_path}"
        )
    return candidate
