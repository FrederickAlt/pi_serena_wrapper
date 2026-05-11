# Use tree-sitter for import extraction instead of the LSP

The `get_document_overview` tool needs to report a file's imports alongside its symbols. SolidLSP cannot resolve definitions for external symbols (stdlib, packages) because `convert_location_item` drops locations outside `repository_root_path`. Regex-based extraction is fragile across language dialects. We chose tree-sitter parsing as the import extraction mechanism.

## Considered Options

- **LSP-based definition resolution**: Send `textDocument/definition` for each top-level symbol to classify local vs. imported. Rejected because external definitions are silently dropped by SolidLSP, conflating "defined externally" with "unresolvable."
- **Regex-based import line extraction**: Simple but fragile — breaks on multi-line imports, type-only imports, dynamic imports, Python `importlib`, etc.
- **Tree-sitter**: Robust grammatical parsing, handles every syntactic edge case, language-agnostic architecture with per-language grammars. Adds native dependencies but all have pre-built wheels.

## Consequences

- New Python dependency: `tree-sitter` plus language grammars (`tree-sitter-python`, `tree-sitter-typescript`)
- New module `bridge/import_parser.py` encapsulates tree-sitter import extraction
- v1 supports TypeScript/TSX and Python only; other languages get a graceful fallback (no imports section)
- Internal imports are resolved to definition locations via `resolve_unique_symbol_via_workspace`; external imports are annotated `[external]`
