"""Self-contained tree-sitter module that extracts imports from source files.

Given source content and a language identifier (``typescript``, ``tsx``, or
``python``), returns a list of ``(original_name, binding_name, source_module)``
triples.  *original_name* is the symbol's canonical name (the one known to
workspace resolution); *binding_name* is the local alias (equals *original_name*
when no alias is present); *source_module* is the module specifier from the
import statement.

Unknown languages return an empty list.

Supports every syntactic edge case:

**TypeScript/TSX**: single imports, multi-imports, default imports, namespace
imports, type-only imports, inline type imports, re-exports (with aliases),
combined default + named, ``require()`` calls, dynamic ``import()`` expressions.

**Python**: ``import X``, ``from X import Y``, ``from X import (a, b, c)``
(multi-line parens), ``from X import Y as Z`` (aliases), ``from .X import Y``
(relative imports with any number of leading dots).

.. note::
    The vendored tree-sitter grammars are listed in ``requirements.txt`` and
    must be installed before use.
"""

from __future__ import annotations

__all__ = ["parse_imports", "parse_imports_file"]

_SUPPORTED_LANGUAGES = ("typescript", "tsx", "python")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_imports(source_code: str, language: str) -> list[tuple[str, str, str]]:
    """Extract ``(original_name, binding_name, source_module)`` triples from *source_code*.

    *language* must be one of ``"typescript"``, ``"tsx"``, or ``"python"``.
    Unknown language identifiers silently return an empty list.
    """
    language = language.lower()
    if language not in _SUPPORTED_LANGUAGES:
        return []

    if language == "python":
        return _parse_python_imports(source_code)
    else:
        return _parse_typescript_imports(source_code, language)


def parse_imports_file(file_path: str, language: str) -> list[tuple[str, str, str]]:
    """Convenience: read *file_path* and run :func:`parse_imports`."""
    with open(file_path, encoding="utf-8") as f:
        source = f.read()
    return parse_imports(source, language)


# ---------------------------------------------------------------------------
# Python import extraction
# ---------------------------------------------------------------------------


def _parse_python_imports(source: str) -> list[tuple[str, str, str]]:
    """Extract imports from Python source via tree-sitter."""
    import tree_sitter_python as tspython
    from tree_sitter import Language, Parser  # type: ignore[import-untyped]

    lang = Language(tspython.language())
    parser = Parser(lang)
    tree = parser.parse(source.encode("utf-8"))
    root_node = tree.root_node

    pairs: list[tuple[str, str, str]] = []
    _walk_python(root_node, pairs)
    return pairs


def _walk_python(node: object, pairs: list[tuple[str, str, str]]) -> None:
    """Walk the tree recursively, dispatching on node type."""
    try:
        ntype = node.type  # type: ignore[union-attr]
    except AttributeError:
        return

    if ntype == "import_statement":
        _handle_py_import_statement(node, pairs)
    elif ntype == "import_from_statement":
        _handle_py_import_from_statement(node, pairs)

    try:
        children = node.children  # type: ignore[union-attr]
    except AttributeError:
        return
    for child in children:
        _walk_python(child, pairs)


def _handle_py_import_statement(
    node: object, pairs: list[tuple[str, str, str]]
) -> None:
    r"""Process ``import os`` or ``import os, sys``."""
    try:
        children = node.children  # type: ignore[union-attr]
    except AttributeError:
        return
    for child in children:
        if getattr(child, "type", "") == "dotted_name":
            text = _node_text(child)
            pairs.append((text, text, text))
        elif getattr(child, "type", "") == "aliased_import":
            # ``import X as Y`` — original is X, binding is Y
            original, alias = _extract_py_aliased_names(child)
            pairs.append((original, alias, original))


def _handle_py_import_from_statement(
    node: object, pairs: list[tuple[str, str, str]]
) -> None:
    r"""Process ``from X import Y``, ``from .X import Y``, ``from X import Y as Z``,
    ``from X import (a,\n b)``."""
    module_text = ""
    dots = 0
    name_nodes: list[object] = []

    try:
        children = node.children  # type: ignore[union-attr]
    except AttributeError:
        return

    for child in children:
        ctype = getattr(child, "type", "")
        if ctype == "dotted_name" and not module_text:
            # First dotted_name after 'from' is the module
            module_text = _node_text(child)
        elif ctype == "relative_import":
            module_text, dots = _extract_py_relative_module(child)
        elif ctype == "dotted_name":
            # Subsequent dotted_names are imported names
            name_nodes.append(child)
        elif ctype == "aliased_import":
            name_nodes.append(child)

    if dots:
        module_text = "." * dots + module_text

    for name_node in name_nodes:
        if getattr(name_node, "type", "") == "aliased_import":
            original, alias = _extract_py_aliased_names(name_node)
            pairs.append((original, alias, module_text))
        else:
            name = _node_text(name_node)
            pairs.append((name, name, module_text))


def _extract_py_relative_module(relative_import_node: object) -> tuple[str, int]:
    """Extract (module_name, dot_count) from a ``relative_import`` node.

    E.g. ``.utils`` → ``("utils", 1)``, ``..base`` → ``("base", 2)``.
    """
    dots = 0
    module_text = ""
    try:
        children = relative_import_node.children  # type: ignore[union-attr]
    except AttributeError:
        return ("", 0)
    for child in children:
        ctype = getattr(child, "type", "")
        if ctype == "import_prefix":
            dots = _node_text(child).count(".")
        elif ctype == "dotted_name":
            module_text = _node_text(child)
    return (module_text, dots)


def _extract_py_aliased_names(aliased_import_node: object) -> tuple[str, str]:
    """From an ``aliased_import`` node like ``Base as B``, extract
    ``("Base", "B")`` — (original_name, alias_name).

    Structure: (aliased_import name:(dotted_name) as alias:(identifier)).
    Falls back to using the first name as both original and alias.
    """
    try:
        children = aliased_import_node.children  # type: ignore[union-attr]
    except AttributeError:
        text = _node_text(aliased_import_node)
        return (text, text)

    identifiers: list[str] = []
    for child in children:
        ctype = getattr(child, "type", "")
        if ctype == "dotted_name":
            identifiers.append(_node_text(child))
        elif ctype == "identifier":
            identifiers.append(_node_text(child))

    if len(identifiers) >= 2:
        return (identifiers[0], identifiers[-1])  # (original, alias)
    elif identifiers:
        return (identifiers[0], identifiers[0])
    text = _node_text(aliased_import_node)
    return (text, text)


# ---------------------------------------------------------------------------
# TypeScript import extraction
# ---------------------------------------------------------------------------


def _parse_typescript_imports(
    source: str, language: str
) -> list[tuple[str, str, str]]:
    """Extract imports from TypeScript/TSX source via tree-sitter."""
    import tree_sitter_typescript as tsts
    from tree_sitter import Language, Parser  # type: ignore[import-untyped]

    if language == "tsx":
        lang = Language(tsts.language_tsx())
    else:
        lang = Language(tsts.language_typescript())

    parser = Parser(lang)
    tree = parser.parse(source.encode("utf-8"))
    root_node = tree.root_node

    pairs: list[tuple[str, str, str]] = []
    _walk_typescript(root_node, pairs)
    return pairs


def _walk_typescript(node: object, pairs: list[tuple[str, str, str]]) -> None:
    """Walk the tree recursively, dispatching on node type."""
    try:
        ntype = node.type  # type: ignore[union-attr]
    except AttributeError:
        return

    if ntype == "import_statement":
        _handle_ts_import_statement(node, pairs)
    elif ntype == "export_statement":
        _handle_ts_export_statement(node, pairs)
    elif ntype == "call_expression":
        _handle_ts_call_expression(node, pairs)

    try:
        children = node.children  # type: ignore[union-attr]
    except AttributeError:
        return
    for child in children:
        _walk_typescript(child, pairs)


def _handle_ts_import_statement(
    node: object, pairs: list[tuple[str, str, str]]
) -> None:
    """Process ``import … from 'module'`` statements.

    Handles: default, named, namespace, type-only, inline type, combined.
    """
    source_specifier = _extract_ts_string(node)
    if source_specifier is None:
        return

    # The import_clause child holds the imported names.
    try:
        children = node.children  # type: ignore[union-attr]
    except AttributeError:
        return

    for child in children:
        if getattr(child, "type", "") == "import_clause":
            _extract_ts_import_clause_names(child, source_specifier, pairs)


def _extract_ts_import_clause_names(
    clause_node: object,
    module_specifier: str,
    pairs: list[tuple[str, str, str]],
) -> None:
    """Walk the import_clause and collect every imported name.

    An import clause can contain, in order:
      * ``identifier`` — default import (``import X``)
      * ``named_imports`` — ``{ a, b }``
      * ``namespace_import`` — ``* as X``
      * Any combination separated by commas (e.g. ``X, { a, b }``).
    """
    try:
        children = clause_node.children  # type: ignore[union-attr]
    except AttributeError:
        return

    for child in children:
        ctype = getattr(child, "type", "")
        if ctype == "identifier":
            # Default import: ``import X from 'module'``
            name = _node_text(child)
            pairs.append((name, name, module_specifier))
        elif ctype == "namespace_import":
            # ``import * as X from 'module'``
            name = _extract_ts_namespace_name(child)
            if name:
                pairs.append((name, name, module_specifier))
        elif ctype == "named_imports":
            _extract_ts_named_imports(child, module_specifier, pairs)


def _handle_ts_export_statement(
    node: object, pairs: list[tuple[str, str, str]]
) -> None:
    """Process re-exports: ``export { X } from 'module'``,
    ``export { X as Y } from 'module'``."""
    source_specifier = _extract_ts_string(node)
    if source_specifier is None:
        return

    try:
        children = node.children  # type: ignore[union-attr]
    except AttributeError:
        return

    for child in children:
        if getattr(child, "type", "") == "export_clause":
            _extract_ts_export_clause_names(child, source_specifier, pairs)


def _extract_ts_export_clause_names(
    clause_node: object,
    module_specifier: str,
    pairs: list[tuple[str, str, str]],
) -> None:
    """Extract names from ``{ X }`` or ``{ X as Y }`` in an export clause."""
    try:
        children = clause_node.children  # type: ignore[union-attr]
    except AttributeError:
        return

    for child in children:
        if getattr(child, "type", "") == "export_specifier":
            result = _extract_ts_export_specifier_names(child)
            if result:
                original, binding = result
                pairs.append((original, binding, module_specifier))


def _extract_ts_export_specifier_names(node: object) -> tuple[str, str] | None:
    """Get (original_name, binding_name) from an ``export_specifier``.
    For ``X`` → ``("X", "X")``, for ``X as Y`` → ``("X", "Y")``."""
    try:
        children = node.children  # type: ignore[union-attr]
    except AttributeError:
        return None

    identifiers: list[str] = []
    for child in children:
        if getattr(child, "type", "") == "identifier":
            identifiers.append(_node_text(child))

    if len(identifiers) >= 2:
        return (identifiers[0], identifiers[-1])  # (original, alias)
    elif identifiers:
        return (identifiers[0], identifiers[0])
    return None


def _extract_ts_named_imports(
    named_imports_node: object,
    module_specifier: str,
    pairs: list[tuple[str, str, str]],
) -> None:
    """Parse ``{ a, b }`` or ``{ a as b }`` or ``{ type a }``."""
    try:
        children = named_imports_node.children  # type: ignore[union-attr]
    except AttributeError:
        return

    for child in children:
        if getattr(child, "type", "") == "import_specifier":
            result = _extract_ts_import_specifier_names(child)
            if result:
                original, binding = result
                pairs.append((original, binding, module_specifier))


def _extract_ts_import_specifier_names(node: object) -> tuple[str, str] | None:
    """Get (original_name, binding_name) from an ``import_specifier``.
    For ``a`` → ``("a", "a")``, for ``a as b`` → ``("a", "b")``,
    for ``type a`` → ``("a", "a")``."""
    try:
        children = node.children  # type: ignore[union-attr]
    except AttributeError:
        return None

    identifiers: list[str] = []
    for child in children:
        if getattr(child, "type", "") == "identifier":
            identifiers.append(_node_text(child))

    if identifiers:
        if len(identifiers) >= 2:
            return (identifiers[0], identifiers[-1])  # (original, alias)
        else:
            return (identifiers[0], identifiers[0])
    return None


def _extract_ts_namespace_name(node: object) -> str | None:
    """Extract the alias from ``* as X``."""
    try:
        children = node.children  # type: ignore[union-attr]
    except AttributeError:
        return None
    for child in children:
        if getattr(child, "type", "") == "identifier":
            return _node_text(child)
    return None


def _handle_ts_call_expression(
    node: object, pairs: list[tuple[str, str, str]]
) -> None:
    """Handle ``require('module')`` and dynamic ``import('module')`` calls."""
    try:
        children = node.children  # type: ignore[union-attr]
    except AttributeError:
        return

    func_name: str | None = None
    string_value: str | None = None

    for child in children:
        ctype = getattr(child, "type", "")
        if ctype == "identifier" and func_name is None:
            func_name = _node_text(child)
        elif ctype == "import" and func_name is None:
            func_name = "import"
        elif ctype == "arguments":
            string_value = _extract_ts_string_from_arguments(child)

    if func_name in ("require", "import") and string_value:
        pairs.append((string_value, string_value, string_value))


def _extract_ts_string_from_arguments(args_node: object) -> str | None:
    """Extract the first string literal inside an arguments node."""
    try:
        children = args_node.children  # type: ignore[union-attr]
    except AttributeError:
        return None
    for child in children:
        if getattr(child, "type", "") == "string":
            return _node_text(child).strip("'\"`")
    return None


def _extract_ts_string(node: object) -> str | None:
    """Find and unquote the ``string`` child of *node*."""
    try:
        children = node.children  # type: ignore[union-attr]
    except AttributeError:
        return None
    for child in children:
        if getattr(child, "type", "") == "string":
            return _node_text(child).strip("'\"`")
    return None


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _node_text(node: object) -> str:
    """Decode the source text of a tree-sitter node."""
    try:
        return node.text.decode("utf-8")  # type: ignore[union-attr]
    except (AttributeError, UnicodeDecodeError):
        return str(node)
