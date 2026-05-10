## name_path

   A `/`-separated path in the symbol tree **within a single source file** (e.g.,
   `MyClass/my_method`). It does **not** include a file path.

   `name_path` is always a **pattern**, not an exact identifier. It is matched
   component-by-component, right-to-left, each component exact:
     - `send` matches any symbol whose last component is `send`
     - `MyClass/send` matches any symbol whose last two components are `MyClass`/`send`
     - `/MyClass/send` (absolute, leading `/`) requires an exact full match

   This applies to all tools (`find_symbol`, `get_references`,
   `get_type`, `get_implementations`, `get_docstring`, `rename_symbol`).

## relative_path

   A path to a source file or directory, relative to the current project root.
   Passed to all tools as an optional scoping parameter.

   Semantics: scopes the symbol search to files under that path. When omitted,
   the search runs project-wide. The only exception is `get_document_symbols`,
   which requires a relative_path because it operates on a single file.

   The bridge canonicalises relative_path before passing it to the LSP:
   it converts to project-root-relative and checks the file exists on disk.

## location

   A compact span string in the format `relative/path:startLine-endLine`
   (e.g. `src/transport.ts:108-130`). Returned by every tool as an
   informational coordinate. Not used for symbol identification — only
   `name_path` is used for identification and resolution.

## code_snippet

   An exact source code string used by `find_symbol` to narrow results via
   `rg --json`. Only symbols whose location falls within a snippet occurrence
   are returned. When `relative_path` is also provided, `rg` is scoped to that
   path; otherwise it searches the entire project.

## tool-contracts.json

   The single source of truth for tool parameter schemas, located at
   `src/tool-contracts.json`. Both `src/schemas.ts` (TypeBox) and
   `bridge/serena_pi_bridge.py` (Python) derive their parameter definitions
   from this file. When adding or changing a tool parameter, update this file
   first, then sync the TypeScript and Python sides.

## SolidLSP

   The vendored LSP backend at `bridge/solidlsp/`. A pure LSP client library
   (MIT licensed) that manages language server processes, sends LSP requests,
   and returns `UnifiedSymbolInformation` trees. The bridge calls SolidLSP
   methods directly — there is no intermediate SerenaAgent layer.
