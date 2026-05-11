"""Context passed to every tool implementation.

Tools depend on this, not the full Bridge.  For tests, construct a
``ToolContext`` with mock language servers — no subprocess, no venv.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from solidlsp import SolidLanguageServer


@dataclass
class ToolContext:
    """Everything a tool needs from the Bridge, and nothing more.

    Four data fields + two dispatch methods.  The Bridge satisfies this
    at runtime; tests construct one with canned values.
    """

    cwd: str
    exclude_dot_paths: bool = True
    overview_kinds: frozenset[int] = field(default_factory=frozenset)

    # Callables — the Bridge wires these to its own methods.
    ls_list_for: object = None     # (relative_path | None) -> list[SolidLanguageServer]
    ls_for_file: object = None     # (relative_path) -> SolidLanguageServer
    language_for_file: object = None  # (relative_path) -> str

    def __post_init__(self) -> None:
        if self.ls_list_for is None:
            raise ValueError("ls_list_for must be provided")
        if self.ls_for_file is None:
            raise ValueError("ls_for_file must be provided")
        if self.language_for_file is None:
            raise ValueError("language_for_file must be provided")
