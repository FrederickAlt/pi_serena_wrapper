"""Context passed to every tool implementation.

Tools depend on this, not the full Bridge.  For tests, construct a
``ToolContext`` with mock language servers — no subprocess, no venv.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from solidlsp import SolidLanguageServer


# ---------------------------------------------------------------------------
# Protocol types — the contract between ToolContext and the Bridge.
# The Bridge wires its own bound methods to these; tests wire mocks.
# ---------------------------------------------------------------------------


class LSListFor(Protocol):
    """Resolve a file/directory to the appropriate LS instance(s).

    ``None`` means project-wide — all configured language servers.
    A file path means the single LS for that file's language.
    A directory path (resolved on disk) means all configured LS instances.
    """
    def __call__(self, relative_path: str | None) -> list[SolidLanguageServer]: ...


class LSForFile(Protocol):
    """Resolve a single file to its language server.

    May lazily start a new language server if the file's language is not yet
    running.
    """
    def __call__(self, relative_path: str) -> SolidLanguageServer: ...


class LanguageForFile(Protocol):
    """Determine the language identifier for a file based on its extension."""
    def __call__(self, relative_path: str) -> str: ...


# ---------------------------------------------------------------------------
# ToolContext
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    """Everything a tool needs from the Bridge, and nothing more.

    Three data fields + three dispatch callables.  The Bridge satisfies this
    at runtime; tests construct one with canned values.
    """

    cwd: str
    exclude_dot_paths: bool = True
    overview_kinds: frozenset[int] = field(default_factory=frozenset)

    # Callables — the Bridge wires its own methods to these.
    ls_list_for: LSListFor = None  # type: ignore[assignment]
    ls_for_file: LSForFile = None  # type: ignore[assignment]
    language_for_file: LanguageForFile = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.ls_list_for is None:
            raise ValueError("ls_list_for must be provided")
        if self.ls_for_file is None:
            raise ValueError("ls_for_file must be provided")
        if self.language_for_file is None:
            raise ValueError("language_for_file must be provided")
