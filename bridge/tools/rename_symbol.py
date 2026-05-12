"""``rename_symbol`` tool — rename a symbol across the project via LSP."""

from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

from solidlsp.ls_utils import PathUtils
from tool_context import ToolContext
from resolution import resolve_tool_symbol


def rename_symbol(params: dict[str, object], ctx: ToolContext) -> str:
    """Rename a symbol throughout the project using direct SolidLSP."""
    new_name = str(params["new_name"])
    resolved = resolve_tool_symbol(params, ctx)

    workspace_edit = resolved.ls.request_rename_symbol_edit(
        resolved.file_path, resolved.line, resolved.column, new_name
    )

    if workspace_edit is None:
        return "Error: rename not supported by this language server"

    applied = 0
    changes_dict: dict[str, list[dict[str, object]]] = workspace_edit.get("changes") or {}
    doc_changes: list[dict[str, object]] = workspace_edit.get("documentChanges") or []

    if not changes_dict and not doc_changes:
        return f"Error: workspace edit for rename of {resolved.raw_params['name_path']!r} is empty"

    rename_ls = resolved.ls

    def _apply_edits(uri_str: str, edits: list[dict[str, object]]) -> str:
        try:
            abs_path = PathUtils.uri_to_path(uri_str)
        except Exception:
            parsed = urllib.parse.urlparse(uri_str)
            abs_path = urllib.parse.unquote(parsed.path)
        try:
            target_relative = os.path.relpath(abs_path, rename_ls.repository_root_path)
        except ValueError:
            target_relative = abs_path

        file_ls = ctx.ls_for_file(target_relative)
        with file_ls.open_file(target_relative) as file_buffer:
            file_ls.apply_text_edits_to_file(target_relative, edits)
            abs_file_path = Path(file_ls.repository_root_path) / target_relative
            abs_file_path.write_text(file_buffer.contents, encoding="utf-8")
        return target_relative

    for uri, edits in changes_dict.items():
        target_relative = _apply_edits(uri, edits)
        applied += 1

    for dc_entry in doc_changes:
        if "textDocument" not in dc_entry:
            continue
        uri = str(dc_entry["textDocument"]["uri"])
        edits = dc_entry.get("edits")
        if not edits or not isinstance(edits, list):
            continue
        target_relative = _apply_edits(uri, edits)
        applied += 1

    if applied == 0:
        return f"Error: no files were modified during rename of {resolved.raw_params['name_path']!r} to {new_name!r}"

    return f"renamed {resolved.raw_params['name_path']} to {new_name}"
