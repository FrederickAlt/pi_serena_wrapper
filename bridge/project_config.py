"""Project configuration — reads and writes ``.serenaproject.yml``.

Extracted from the Bridge.  Parses the YAML config once and returns a typed
``ProjectConfig`` dataclass.  Auto-detection and default-config writing are
separate concerns that the Bridge orchestrates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from solidlsp.ls_types import SymbolKind


# ---------------------------------------------------------------------------
# Shared constant (source of truth for document overview default kinds)
# ---------------------------------------------------------------------------

DEFAULT_DOCUMENT_OVERVIEW_KINDS: frozenset[int] = frozenset({
    SymbolKind.Module,        # 2
    SymbolKind.Namespace,     # 3
    SymbolKind.Class,         # 5
    SymbolKind.Method,        # 6
    SymbolKind.Constructor,   # 9
    SymbolKind.Enum,          # 10
    SymbolKind.Interface,     # 11
    SymbolKind.Function,      # 12
    SymbolKind.Struct,        # 23
    SymbolKind.Event,         # 24
    SymbolKind.TypeParameter, # 26
})


# ---------------------------------------------------------------------------
# ProjectConfig
# ---------------------------------------------------------------------------

@dataclass
class ProjectConfig:
    """Typed representation of ``.serenaproject.yml``."""
    languages: list[str] = field(default_factory=list)
    document_overview_default_kinds: frozenset[int] = field(
        default_factory=lambda: DEFAULT_DOCUMENT_OVERVIEW_KINDS,
    )
    exclude_dot_paths: bool = True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_project_config(project_root: str) -> ProjectConfig:
    """Read ``.serenaproject.yml`` and return a ``ProjectConfig``.

    Returns a default config (empty languages, default kinds,
    exclude_dot_paths=True) when the file is absent or unparseable.
    """
    config_path = Path(project_root) / ".serenaproject.yml"
    if not config_path.is_file():
        return ProjectConfig()

    try:
        with open(config_path, encoding="utf-8") as f:
            cfg: object = yaml.safe_load(f)
    except yaml.YAMLError:
        return ProjectConfig()

    if not isinstance(cfg, dict):
        return ProjectConfig()

    return ProjectConfig(
        languages=_parse_languages(cfg),
        document_overview_default_kinds=_parse_kinds(cfg),
        exclude_dot_paths=bool(cfg.get("exclude_dot_paths", True)),
    )


def detect_languages(project_root: str) -> list[str]:
    """Auto-detect the primary language(s) from the project file structure."""
    root = Path(project_root)
    # TypeScript
    if (list(root.glob("tsconfig.json"))
            or list(root.glob("*.ts"))
            or list(root.glob("src/**/*.ts"))
            or list(root.glob("*.tsx"))
            or list(root.glob("src/**/*.tsx"))):
        return ["typescript"]
    # Python
    if (list(root.glob("*.py"))
            or list(root.glob("src/**/*.py"))
            or list(root.glob("pyproject.toml"))
            or list(root.glob("setup.py"))
            or list(root.glob("setup.cfg"))):
        return ["python"]
    return ["typescript"]  # safe default


def write_default_config(project_root: str, languages: list[str]) -> None:
    """Write a default ``.serenaproject.yml`` if one does not already exist."""
    config_path = Path(project_root) / ".serenaproject.yml"
    if config_path.is_file():
        return  # already exists

    default_kind_names = sorted(
        SymbolKind(k).name for k in sorted(DEFAULT_DOCUMENT_OVERVIEW_KINDS)
    )
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            {
                "languages": languages,
                "document_overview_default_kinds": default_kind_names,
            },
            f,
            default_flow_style=False,
        )


# ---------------------------------------------------------------------------
# Internal parsers
# ---------------------------------------------------------------------------

def _parse_languages(cfg: dict) -> list[str]:
    raw = cfg.get("languages")
    if not raw or not isinstance(raw, list):
        return []
    return [str(l) for l in raw if isinstance(l, str)]


def _parse_kinds(cfg: dict) -> frozenset[int]:
    raw: list[str] | None = cfg.get("document_overview_default_kinds")
    if not raw or not isinstance(raw, list):
        return DEFAULT_DOCUMENT_OVERVIEW_KINDS
    result: set[int] = set()
    for name in raw:
        if not isinstance(name, str):
            continue
        try:
            result.add(SymbolKind[name].value)
        except KeyError:
            raise ValueError(
                f"Unknown SymbolKind name in .serenaproject.yml "
                f"document_overview_default_kinds: {name!r}"
            ) from None
    return frozenset(result) if result else DEFAULT_DOCUMENT_OVERVIEW_KINDS
