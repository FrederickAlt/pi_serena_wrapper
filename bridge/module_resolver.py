"""Pluggable language-specific module-path resolution.

Each language registers a callable ``(module: str, file_relative_path: str)
-> list[str]`` that returns the set of **expected project-relative file
paths** an import of *module* could resolve to from *file_relative_path*.

Callers use :func:`ModuleResolver.get` to obtain a resolver for a given
language name.
"""

from __future__ import annotations

import os
from typing import Callable


#: Signature for a language-specific module resolver.
ResolverFn = Callable[[str, str], list[str]]


class ModuleResolver:
    """Registry of per-language module-path resolvers."""

    _resolvers: dict[str, ResolverFn] = {}

    @classmethod
    def register(cls, language: str, fn: ResolverFn) -> None:
        """Register *fn* as the resolver for *language* (case-insensitive)."""
        cls._resolvers[language.lower()] = fn

    @classmethod
    def get(cls, language: str) -> ResolverFn | None:
        """Return the resolver for *language*, or ``None``."""
        return cls._resolvers.get(language.lower())


# ---------------------------------------------------------------------------
# Python resolver
# ---------------------------------------------------------------------------


def _resolve_python_module_paths(module: str, file_relative_path: str) -> list[str]:
    """Return expected file paths for a non-relative Python import.

    Walks up the importing file's directory hierarchy.  At each level
    (including the project root), generates a candidate ``.py`` file and
    ``/__init__.py`` directory.

    Example: ``formatting`` from ``bridge/tools/find_symbol.py`` returns:
    ``["bridge/tools/formatting.py", "bridge/tools/formatting/__init__.py",
       "bridge/formatting.py", "bridge/formatting/__init__.py",
       "formatting.py", "formatting/__init__.py"]``
    """
    module_path = module.replace(".", "/")
    file_dir = os.path.dirname(file_relative_path) if file_relative_path else ""
    parts = [p for p in file_dir.split("/") if p] if file_dir else []

    candidates: list[str] = []

    # Walk up from the file's directory to the project root.
    # i = 0 → project root; i = n → full directory path.
    for i in range(len(parts), -1, -1):
        prefix = "/".join(parts[:i]) if i > 0 else ""
        if prefix:
            candidates.append(f"{prefix}/{module_path}.py")
            candidates.append(f"{prefix}/{module_path}/__init__.py")
        else:
            candidates.append(f"{module_path}.py")
            candidates.append(f"{module_path}/__init__.py")

    return candidates


# Register the Python resolver on import.
ModuleResolver.register("python", _resolve_python_module_paths)
ModuleResolver.register("py", _resolve_python_module_paths)
