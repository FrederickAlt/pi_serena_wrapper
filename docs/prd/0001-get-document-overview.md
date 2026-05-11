# PRD: `get_document_overview` — File overview with imports and line ranges

## Problem Statement

When an agent wants to understand what a source file does, the current `get_document_symbols` tool only shows a structural outline: `Class UserService`, `Method create`, etc. The agent can't tell at a glance *where* each symbol's body lives in the file (line numbers) or *what the file depends on* (imports). The agent must make separate tool calls — `read` for the file, `find_symbol` / `get_references` for dependency resolution — turning a simple "what does this file do?" into a multi-step investigation.

## Solution

Replace `get_document_symbols` with `get_document_overview`. The new tool returns a two-section plain-text overview:

- **`## Imports`** — what the file consumes, extracted via tree-sitter parsing. Each source module is listed with its imported names. Internal imports (project-local) are resolved to definition locations; external imports (stdlib/packages) are annotated as `[external]`.
- **`## Symbols`** — what the file defines, each with its body line range (e.g., `Class UserService:5-67`). Imported bindings are excluded so the symbols section shows only locally-defined constructs.

A single tool call replaces the agent's current workflow of `get_document_symbols` + `read` + multiple LSP lookups.

## User Stories

1. As an agent, I want to see the line range of each symbol in a file (e.g., `Function validate:12-30`), so that I know exactly where each symbol's body lives without opening the file.
2. As an agent, I want to see all imports a file depends on, grouped by source module, so that I understand the file's dependency footprint at a glance.
3. As an agent, I want internal imports (project-local) resolved to their definition file and line range, so that I can navigate to the definition without a separate `find_symbol` / `get_type` call.
4. As an agent, I want external imports (stdlib, packages) clearly annotated as `[external]`, so that I know they are not navigable within the project.
5. As an agent, I want the symbols section to show only symbols defined in this file (not imported bindings), so that I can distinguish between what the file provides vs. what it consumes.
6. As an agent, I want to control the nesting depth of the symbols tree via a `depth` parameter, so that I can get a collapsed top-level view or an expanded drill-down.
7. As an agent working with TypeScript or Python code, I want robust import parsing that handles every syntactic edge case (multi-line imports, type-only imports, aliases, re-exports), so that I can trust the imports section.
8. As an agent working with other languages, I want the symbols section to still work, so that the tool is useful even when import parsing isn't available for my language.

## Implementation Decisions

### Tool contract

- **Tool name**: `get_document_overview`
- **Removes**: `get_document_symbols` (immediate removal; the two-section output covers the old use case)
- **Parameters**:
  - `relative_path` (string, required) — path to the source file
  - `depth` (number, optional, default 0) — descendant nesting depth for the symbols tree

### Output format

Two Markdown-heading sections:

```
## Imports
./utils — validate, formatDate            [internal → src/utils.ts:1-3]
react — useState, useEffect               [external]
matplotlib — pyplot (as plt)             [external]
../models — User                          [internal → src/models.ts:5-8]

## Symbols
Class UserService:5-67
  Method create:12-43
  Method delete:45-66
Function helper:69-80
```

Each imports line: `<module> — <names> [classification]`. Multiple names from the same module are comma-separated. Names with aliases (e.g., `plt` aliasing `pyplot`) are shown as `pyplot (as plt)`.

Each symbols line: `Kind Name:startLine-endLine`. Indentation is 2 spaces per nesting level. Line numbers are zero-based from `location.range`.

When import resolution fails for an internal import, the annotation falls back to `[internal]` without a location. The overview always returns a best-effort result — no errors on resolution failures.

### Import extraction

Tree-sitter parsing in a dedicated module. Takes file content and language identifier, returns a list of `(name, source_module)` pairs. Supports TypeScript/TSX and Python in v1. Unknown languages return an empty list (imports section is omitted).

### Import classification and resolution

Source modules are classified as internal or external based on the module specifier: relative paths (`./`, `../`) and project-known names are internal; standard library paths and third-party package names are external.

For internal imports, each imported name is resolved to a definition location via workspace symbol search (one LSP call per name), scoped to the source module's directory. When resolution returns a unique symbol, the definition location is shown. When ambiguous or not found, the fallback `[internal]` annotation is used.

### Symbol extraction and filtering

Symbols come from the existing LSP `textDocument/documentSymbol` request (unchanged mechanism). Imported names identified by tree-sitter are filtered out so the symbols section shows only locally-defined symbols. Each symbol is formatted with its kind name and body line range from `location.range`.

### v1 language scope

Import parsing: TypeScript/TSX, Python. Other languages: imports section omitted, symbols section works via LSP as before.

### Architectural shape

- New deep module `import_parser.py` encapsulates all tree-sitter import extraction behind a single function. Testable in isolation with fixture files.
- Bridge orchestrates: parse imports → classify → resolve internal → format symbols → combine into output.
- TypeScript side registers the tool with pi, passes parameters to the bridge as JSON.

## Testing Decisions

### What makes a good test

- Test module interfaces, not internal implementation details.
- For `import_parser.py`: given a source file snippet (TypeScript or Python), assert the parsed import list (names, source modules).
- For the integration test: given a project fixture, call `get_document_overview` via JSONL and assert the output text matches expected format. Follows the existing pattern in `scripts/jsonl-regression.ts`.

### Modules tested

1. `import_parser.py` — unit tests (new, similar to `test_name_path.py`). Test TypeScript and Python import extraction across edge cases: single imports, multi-imports, aliases, default imports, type-only imports, re-exports.
2. `serena_pi_bridge.py::_get_document_overview` — integration test via the existing JSONL regression suite. Create TypeScript and Python fixtures with imports and symbols, assert the two-section output.

### Test order

Unit tests for `import_parser.py` first (red-green-refactor), then integration test.

### Prior art

- `bridge/test_name_path.py` — unit test file for `name_path.py`, using pytest fixtures.
- `scripts/jsonl-regression.ts` — end-to-end regression test that exercises every tool against temporary TypeScript and Python fixtures.

## Out of Scope

- Import parsing for languages other than TypeScript/TSX and Python.
- Resolving external imports to their package definition locations (SolidLSP cannot do this).
- Showing the actual import *lines* in the imports section (the section shows parsed and classified imports, not raw source lines).
- A `resolve_imports` toggle to skip resolution — always resolves, always falls back gracefully.
- Modifying `get_document_symbols` to return line ranges (it's being removed).

## Further Notes

- The tree-sitter decision is documented in `docs/adr/0002-tree-sitter-for-import-extraction.md`.
- `CONTEXT.md` has been updated with the new glossary terms: `get_document_overview`, `internal import`, `external import`, `tree-sitter`.
- The prompt guidelines for `get_document_symbols` in `AGENTS.md` will be re-purposed for `get_document_overview`.
