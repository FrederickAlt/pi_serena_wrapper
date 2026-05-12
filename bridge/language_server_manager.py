"""Language server lifecycle manager.

Owns the ``_ls_map``, start/stop, and per-file dispatch.  Extracted from the
Bridge so tools and tests can reason about language servers without touching
the JSONL protocol or config I/O.
"""

from __future__ import annotations

import sys
from pathlib import Path

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.settings import SolidLSPSettings


class LanguageServerManager:
    """Manages one ``SolidLanguageServer`` per configured language.

    Owns starting, stopping, lazy-start, and per-file dispatch.
    Exposes compat properties (``ls``, ``cwd``, ``language``, ``languages``,
    ``ls_map``) so code that used to read them from ``Bridge`` continues
    to work.
    """

    # File extension → language identifier for per-file dispatch.
    _EXT_TO_LANGUAGE: dict[str, str] = {
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "typescript",
        ".jsx": "typescript",
        ".mts": "typescript",
        ".mjs": "typescript",
        ".cts": "typescript",
        ".cjs": "typescript",
        ".py": "python",
        ".pyi": "python",
    }

    def __init__(self) -> None:
        self._ls_map: dict[str, SolidLanguageServer] = {}
        self._languages: list[str] = []
        self.cwd: str | None = None
        self._primary_language: str | None = None

    # -- compat / readability properties -----------------------------------

    @property
    def ls(self) -> SolidLanguageServer | None:
        """The primary (first-configured) language server."""
        if self._primary_language:
            return self._ls_map.get(self._primary_language)
        if self._ls_map:
            return next(iter(self._ls_map.values()))
        return None

    @property
    def language(self) -> str | None:
        """The primary language identifier."""
        return self._primary_language

    @property
    def languages(self) -> list[str]:
        """All configured language identifiers (in-order)."""
        return list(self._languages)

    @property
    def ls_map(self) -> dict[str, SolidLanguageServer]:
        """The internal language → server dict (read-only view)."""
        return dict(self._ls_map)

    # -- lifecycle ----------------------------------------------------------

    def start(self, project_root: str, languages: list[str]) -> None:
        """Start a language server for every configured language."""
        if not languages:
            raise ValueError("languages must not be empty")

        settings = SolidLSPSettings(
            solidlsp_dir=str(Path.home() / ".solidlsp"),
            project_data_path=str(Path(project_root) / ".solidlsp"),
        )

        self._ls_map = {}
        for lang_name in languages:
            lang = Language(lang_name)
            config = LanguageServerConfig(
                code_language=lang,
                encoding="utf-8",
            )
            ls_instance = SolidLanguageServer.create(
                config, project_root, solidlsp_settings=settings
            )
            ls_instance.start()
            self._ls_map[str(lang)] = ls_instance

        self._languages = list(languages)
        self._primary_language = str(Language(languages[0]))
        self.cwd = project_root

    def shutdown(self) -> None:
        """Stop all language servers cleanly."""
        for ls_instance in self._ls_map.values():
            try:
                ls_instance.stop()
            except Exception:
                pass
        self._ls_map = {}
        self._languages = []
        self._primary_language = None
        self.cwd = None

    # -- per-file dispatch --------------------------------------------------

    def language_for_file(self, relative_path: str) -> str:
        """Return the language identifier for *relative_path* based on extension.

        Falls back to the primary language when the extension is unrecognised.
        """
        suffix = Path(relative_path).suffix.lower()
        if suffix in self._EXT_TO_LANGUAGE:
            return self._EXT_TO_LANGUAGE[suffix]
        return self._primary_language or ""

    def ls_list_for(self, relative_path: str | None) -> list[SolidLanguageServer]:
        """Return the appropriate LS instances to search.

        * ``None`` → all configured LS instances (project-wide search).
        * A file path → the single LS for that file's language.
        * A directory path (resolved on disk) → all configured LS instances.
        """
        if relative_path is not None:
            if self.cwd is not None:
                abs_path = Path(self.cwd) / relative_path
                if abs_path.is_dir():
                    return list(self._ls_map.values())
            return [self.ls_for_file(relative_path)]
        return list(self._ls_map.values())

    def ls_for_file(self, relative_path: str) -> SolidLanguageServer:
        """Return the language server for *relative_path*.

        Lazily starts a new language server when the file's language is
        recognised but not yet running.
        """
        language = self.language_for_file(relative_path)
        if language in self._ls_map:
            return self._ls_map[language]

        # Falls back to primary when extension is unrecognised.
        if language == self._primary_language:
            primary = self.ls
            if primary is not None:
                return primary
            raise RuntimeError("No primary language server available")

        # Recognised extension, no running server → lazy start.
        return self.start_language_lazily(language)

    def start_language_lazily(self, language: str) -> SolidLanguageServer:
        """Start a language server for *language* on demand.

        Validates with SolidLSP, creates and starts a server, and appends
        the language to the in-memory tracking list.  Does **not** mutate
        ``.serenaproject.yml`` on disk — the lazy start is transient.
        """
        assert self.cwd is not None

        print(
            f"[pi-serena-lsp] lazily starting {language} language server...",
            file=sys.stderr,
        )

        # Validate that SolidLSP knows this language.
        try:
            lang = Language(language)
        except ValueError as exc:
            raise ValueError(
                f"Language {language!r} is not supported by SolidLSP. "
                f"Known languages: {sorted(l.value for l in Language)}"
            ) from exc

        lang_str = str(lang)

        config = LanguageServerConfig(code_language=lang, encoding="utf-8")
        settings = SolidLSPSettings(
            solidlsp_dir=str(Path.home() / ".solidlsp"),
            project_data_path=str(Path(self.cwd) / ".solidlsp"),
        )
        ls_instance = SolidLanguageServer.create(
            config, self.cwd, solidlsp_settings=settings
        )
        ls_instance.start()

        self._ls_map[lang_str] = ls_instance
        if lang_str not in self._languages:
            self._languages.append(lang_str)

        return ls_instance
