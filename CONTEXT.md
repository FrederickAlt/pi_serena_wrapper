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
   the search runs project-wide. The only exception is `get_document_overview`, which requires a relative_path
   because it operates on a single file.

   The bridge validates relative_path before use: it resolves the path
   against the project root, enforces containment (rejecting absolute-path
   bypass, ``..`` traversal, and symlink escapes), and checks the file
   exists on disk.

## get_document_overview

   Returns a two-section plain-text overview of a
   single file: `## Imports` (what the file consumes) and `## Symbols` (what the
   file defines). Each symbol line includes its 1-based body line range:
   `Class UserService:5-67`. Line numbers are 1-based, consistent with pi's
   `read` and `write` tools.

   The imports section is extracted via tree-sitter parsing (not LSP) because
   SolidLSP drops external definition locations. Imports are classified:
     - **internal** — resolved to a definition location via LSP workspace symbol
       search, shown as `[internal → path:lines]`
     - **external** — standard library or package, shown as `[external]`
     - When resolution fails, internal imports fall back to `[internal]` without
       a location.

   The symbols section shows only locally-defined symbols (imported bindings are
   excluded). Nesting depth is controlled by the `depth` parameter (0 = top-level
   only).

   v1 supports TypeScript/TSX and Python import parsing. Other languages omit the
   imports section.

## overview entry

   A rendered declaration row in the `## Symbols` section, selected by the overview's `category`, `depth`, and visibility rules.

## shape preview

   A compact, bounded source-derived summary nested under a structural overview entry, such as interface fields, enum members, a type alias shape, or a compact class member list.

## category

   A language-neutral filter label for overview entries, such as `function`, `class`, `type`, or `constant`; it is not a raw Tree-sitter node type or an LSP `SymbolKind`.

## Flagged ambiguities

## SolidLSP

   The vendored LSP backend at `bridge/solidlsp/`. A pure LSP client library
   (MIT licensed) that manages language server processes, sends LSP requests,
   and returns `UnifiedSymbolInformation` trees. The bridge calls SolidLSP
   methods directly — there is no intermediate SerenaAgent layer.
