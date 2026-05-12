"""Import classification extracted from the Bridge.

Takes parsed import triples (from ``import_parser``) and a language server
instance, and returns a formatted imports section string with each source
module classified as ``[internal → path:lines]`` or ``[external]``.

The only public entry point is ``format_imports_section``.
"""

from __future__ import annotations

import os
from collections import defaultdict

from solidlsp import SolidLanguageServer

from name_path import resolve_unique_symbol_via_workspace, SymbolResolutionError
from module_resolver import ModuleResolver


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def format_imports_section(
    import_pairs: list[tuple[str, str, str]],
    file_relative_path: str,
    ls: SolidLanguageServer,
) -> str:
    """Group imports by source module and produce one line per module.

    Displays ``original (as binding)`` only when the two names differ.
    Resolves via *original_name* (the workspace-known symbol).

    Returns the full ``## Imports`` section body (without the header).
    """
    by_module: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for original, binding, module in import_pairs:
        by_module[module].append((original, binding))

    lines: list[str] = []
    for module, name_pairs in sorted(by_module.items()):
        seen: set[tuple[str, str]] = set()
        display_names: list[str] = []
        for original, binding in name_pairs:
            key = (original, binding)
            if key in seen:
                continue
            seen.add(key)
            if original == binding:
                display_names.append(original)
            else:
                display_names.append(f"{original} (as {binding})")
        names_str = ", ".join(display_names)
        # Use original names for workspace resolution (deduplicated)
        seen_orig: set[str] = set()
        original_names: list[str] = []
        for orig, _ in name_pairs:
            if orig not in seen_orig:
                seen_orig.add(orig)
                original_names.append(orig)
        classification = _classify_import(module, original_names, file_relative_path, ls)
        lines.append(f"{module} — {names_str} {classification}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_import(
    module: str,
    names: list[str],
    file_relative_path: str,
    ls: SolidLanguageServer,
) -> str:
    """Classify a source module as internal or external.

    Relative module paths (starting with ``.``) are always internal.
    Non-relative modules are resolved via workspace symbol search and
    verified to ensure the resolved definition actually belongs to the
    imported module (not an internal name collision).
    """
    # Relative import — definitely internal
    if module.startswith("."):
        location = _resolve_import_location(names, file_relative_path, module, ls)
        if location:
            return f"[internal → {location}]"
        return "[internal]"

    # Non-relative — try to resolve names via workspace symbol search.
    location = _resolve_import_location(names, file_relative_path, module, ls)
    if location is None:
        return "[external]"

    # If a language-specific module resolver is available, use it to
    # verify that the resolved file actually matches the expected module
    # path.  This eliminates false positives from same-named files in
    # unrelated directories.
    language = _language_from_path(file_relative_path)
    resolver = ModuleResolver.get(language)
    if resolver is not None:
        expected_paths = resolver(module, file_relative_path)
        if _any_resolved_file_matches(location, expected_paths):
            return f"[internal → {location}]"
        # Exact match failed — fall back to lenient name-based check.
        # Handles cases the resolver can't model (e.g. sys.path entries
        # in directories outside the importing file's ancestor chain).
        # We accept the lenient match rather than risk a false negative
        # (classifying an internal module as external).
        if _verify_module_file_match(location, module):
            return f"[internal → {location}]"
        return "[external]"

    # Fallback: no module resolver for this language.  We have workspace
    # candidates but can't disambiguate which file the import truly
    # resolves to.  Err on the side of [internal] — shadowing external
    # package names with internal modules is bad practice anyway.
    return f"[internal → {location}]"


def _resolve_import_location(
    names: list[str],
    file_relative_path: str,
    module: str,
    ls: SolidLanguageServer,
) -> str | None:
    """Try to resolve imported names to a definition location.

    Resolves **every** name in *names* and returns a location string of
    the form ``"rel/path:start-end&start-end..."`` — one range per
    resolved name, joined with ``&``.  Returns ``None`` if no name
    resolves successfully.

    For relative module specifiers (starting with ``.``), the search
    scope is computed by resolving *module* against the file's parent
    directory, so cross-directory imports (e.g. ``../src/foo``) scope
    correctly.  For non-relative specifiers the scope is the project
    root (``None``), since bare module names resolve from the project
    root, not the file's own directory.
    """
    raw_dir = os.path.dirname(file_relative_path)
    if module.startswith("."):
        base_dir = raw_dir or "."
        if "/" in module:
            resolved = os.path.normpath(os.path.join(base_dir, module))
        else:
            resolved = _resolve_python_module(base_dir, module)
        scope_dir = os.path.dirname(resolved) or None
    else:
        scope_dir = None  # project-wide; bare names resolve from project root

    ranges: list[tuple[str, int, int]] = []
    for name in names:
        try:
            symbol = resolve_unique_symbol_via_workspace(
                [ls], name, relative_path=scope_dir
            )
        except SymbolResolutionError as exc:
            # Ambiguity — collect all candidate locations.
            for candidate in exc.candidates:
                loc_str = candidate.get("location", "")
                if ":" in str(loc_str):
                    file_part, range_part = str(loc_str).split(":", 1)
                    if "-" in range_part:
                        start_str, end_str = range_part.split("-", 1)
                        try:
                            ranges.append((file_part, int(start_str), int(end_str)))
                        except ValueError:
                            pass
            continue
        except Exception:
            continue

        location = symbol.get("location") or {}
        rel_path = location.get("relativePath")
        rng = location.get("range") or {}
        start = rng.get("start", {}).get("line", 0) + 1
        end = rng.get("end", {}).get("line", 0) + 1

        if rel_path:
            ranges.append((rel_path, start, end))

    if not ranges:
        return None

    unique_files = list(dict.fromkeys(p for p, _, _ in ranges))
    if len(unique_files) == 1:
        base_path = unique_files[0]
        range_strs = [f"{s}-{e}" for _, s, e in ranges]
        return f"{base_path}:{'&'.join(range_strs)}"
    else:
        parts: list[str] = []
        for p, s, e in ranges:
            parts.append(f"{p}:{s}-{e}")
        return "; ".join(parts)


def _verify_module_file_match(location: str, module: str) -> bool:
    """Check that a resolved symbol location actually belongs to the
    imported *module* rather than being an unrelated internal name
    collision.
    """
    resolved_files: list[str] = []
    for part in location.split("; "):
        fpath = part.split(":")[0] if ":" in part else part
        if fpath:
            resolved_files.append(fpath)
    if not resolved_files:
        return False

    module_path = module.replace(".", "/")

    def _path_matches_module(fpath: str) -> bool:
        normalized = fpath.replace("\\", "/")
        stem = normalized
        for ext in (".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts", ".cts", ".cjs"):
            if stem.endswith(ext):
                stem = stem[: -len(ext)]
                break
        return (
            stem == module_path
            or stem.endswith(f"/{module_path}")
            or f"/{module_path}/" in stem
            or stem == f"{module_path}/__init__"
            or stem.endswith(f"/{module_path}/__init__")
            or stem == f"{module_path}/index"
            or stem.endswith(f"/{module_path}/index")
        )

    return any(_path_matches_module(f) for f in resolved_files)


def _language_from_path(file_relative_path: str) -> str:
    """Infer language name from a file extension."""
    ext = os.path.splitext(file_relative_path)[1].lower()
    if ext in (".py", ".pyi"):
        return "python"
    if ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts", ".cts", ".cjs"):
        return "typescript"
    return "unknown"


def _any_resolved_file_matches(location: str, expected_paths: list[str]) -> bool:
    """Check that at least one resolved file in *location* appears in
    the *expected_paths* list (exact match, sans range)."""
    resolved_files: set[str] = set()
    for part in location.split("; "):
        fpath = part.split(":")[0] if ":" in part else part
        if fpath:
            resolved_files.add(fpath)
    if not resolved_files:
        return False
    return bool(resolved_files & set(expected_paths))


def _resolve_python_module(file_dir: str, module: str) -> str:
    """Resolve a Python-style relative module specifier to a filesystem path.

    Python relative imports use leading dots for depth and dots as module
    separators: ``.utils`` (same package), ``..src.utils`` (parent → src/utils).

    Returns a normalized relative path (e.g. ``src/utils``).
    """
    depth = 0
    rest = module
    while rest.startswith("."):
        depth += 1
        rest = rest[1:]

    module_path = rest.replace(".", "/") if rest else ""

    up = file_dir
    for _ in range(depth - 1):
        up = os.path.dirname(up) or "."

    if module_path:
        return os.path.normpath(os.path.join(up, module_path))
    return os.path.normpath(up)
