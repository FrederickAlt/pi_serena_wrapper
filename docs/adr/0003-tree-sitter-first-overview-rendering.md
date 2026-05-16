# Tree-sitter-first overview rendering

We will render the `get_document_overview` Symbols section from project-owned Tree-sitter overview queries where a language renderer exists, starting with TypeScript/TSX. LSP document symbols remain the fallback for unsupported languages or renderer failures, and LSP remains responsible for semantic operations such as import definition resolution, references, hover, type lookup, implementations, and rename.

## Considered Options

- **LSP-first rendering**: preserves current implementation but keeps noisy IDE-oriented symbols and weak source-shape output.
- **Tree-sitter-only rendering**: gives fast local syntax and better declaration/shape extraction, but loses existing semantic import-location resolution and cross-language fallback.
- **Tree-sitter-first with LSP fallback/enrichment**: chosen because local file overview is primarily syntactic, while cross-file semantic lookup remains better served by LSP.

## Consequences

The bridge owns vendored `.scm` overview queries instead of trusting upstream `tags.scm` completeness. Language knowledge should live primarily in those query files, with only small language-specific adapters when unavoidable. The first complete renderer is TypeScript/TSX; other languages continue to use LSP fallback until implemented through the same query-contract architecture.
