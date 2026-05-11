# agent.md — pi-serena-lsp

## What this is

A **pi extension** that exposes SolidLSP-backed symbolic LSP tools as pi tools. When the pi harness loads this extension, it registers 8 tools (`find_symbol`, `get_document_symbols`, `get_document_overview`, `get_type`, `get_references`, `get_implementations`, `get_docstring`, `rename_symbol`) that let an agent query the project's symbol index through a language server.

The extension is a thin bridge between two runtimes: the pi agent (Node.js/TypeScript) and a vendored SolidLSP (Python). The Node side registers tools, manages per-project bridge clients, and sends JSON-RPC requests over stdin/stdout to a Python subprocess that wraps `SolidLanguageServer`.

---

## Repository layout

```
pi-serena-lsp/
├── src/                        # TypeScript — pi extension
│   ├── extension.ts            # Entry point: registers 8 tools, manages clients
│   ├── schemas.ts              # TypeBox parameter schemas (synced with tool-contracts.json)
│   ├── bridge-client.ts        # Node JSONL client: spawns Python bridge, sends requests
│   ├── transport.ts            # JSON-RPC transport via subprocess stdin/stdout
│   └── tool-contracts.json     # Shared JSON schema — single source of truth for tool params
├── bridge/                     # Python — bridge backend
│   ├── serena_pi_bridge.py     # JSONL server: starts SolidLSP, routes tool calls
│   ├── name_path.py            # Symbol name_path computation, matching, resolution
│   ├── import_parser.py        # Tree-sitter import extraction (used by get_document_overview)
│   ├── test_name_path.py       # Unit tests for name_path logic
│   └── solidlsp/               # Vendored SolidLSP (MIT) — the LSP backend
├── scripts/
│   └── jsonl-regression.ts     # Regression test — exercises every tool against TS/Python fixtures
├── docs/
│   └── adr/                    # Design decisions made
│       └── 0001-remove-bridge-language-detection.md
├── package.json                # pi extension manifest (pi.extensions → src/extension.ts)
├── tsconfig.json               # TypeScript config (noEmit, type-check only)
└── requirements.txt            # Python deps for vendored solidlsp (sensai-utils, pathspec, jsonschema, pyyaml)
```

---

## Architecture

```
pi harness (Node/TS)  ──JSONL over stdin/stdout──►  serena_pi_bridge.py (Python)
                                                           │
                                                           ▼
                                                     SolidLanguageServer (vendored SolidLSP)
```

- **`src/extension.ts`** — Loaded by pi at startup. Calls `pi.registerTool()` for each of the 7 tool names. Maintains one `SerenaBridgeClient` instance; on `session_shutdown` it kills the Python process.
- **`src/bridge-client.ts`** — Spawns `bridge/serena_pi_bridge.py` via the local `.venv` Python. Sends `init`, `call_tool`, `shutdown` commands. Ensures the Python venv is set up before starting. Tracks the current `cwd` so switching projects re-inits the language server.
- **`src/transport.ts`** — `SubprocessTransport` class: spawns the Python process, reads JSONL from stdout, writes to stdin. Handles timeouts (default 240s), abort signals, stderr capture, and `SerenaError` extraction.
- **`bridge/serena_pi_bridge.py`** — `Bridge` class: starts a `SolidLanguageServer` on `init`, dispatches 7 tool calls directly to SolidLSP methods. Validates arguments against `tool-contracts.json` before dispatch.
- **`bridge/name_path.py`** — `compute_name_path`: walks a symbol's `parent` chain to produce a `/`-separated path (e.g. `MyClass/my_method`). `NamePathMatcher`: component-by-component, right-to-left pattern matching. `resolve_unique_symbol`: project-wide name_path resolution with ambiguity handling.
- **`src/tool-contracts.json`** — The canonical parameter definitions. **Both `schemas.ts` and `serena_pi_bridge.py` derive from this file.** If you add or change a tool parameter, update this file first, then sync the TypeBox and Python validation.

---

## 7 tools and where they live

| Tool | Responsibility | Dispatch in bridge | Relevant contract |
|---|---|---|---|
| `find_symbol` | Search the symbol tree by name_path pattern | Flattens `request_full_symbol_tree`, matches via `NamePathMatcher`, optionally filters by `code_snippet` (rg) and `kinds` | `tool-contracts.json:find_symbol` |
| `get_document_symbols` | *(deprecated)* Indented text tree of symbols in a file | `ls.request_document_symbols`, recursive formatting | `tool-contracts.json:get_document_symbols` |
| `get_document_overview` | Two-section overview: Imports (classified) + Symbols (with line ranges) | `parse_imports` → classify/resolve → `request_document_symbols` → filter imported bindings → format | `tool-contracts.json:get_document_overview` |
| `get_type` | Resolve a name_path to its defining type | `resolve_unique_symbol` → `ls.request_defining_symbol` | `tool-contracts.json:get_type` |
| `get_references` | Find all references to a symbol | `resolve_unique_symbol` → `ls.request_references` → resolve each symbol at reference location | `tool-contracts.json:get_references` |
| `get_implementations` | Find interface/abstract implementations | `resolve_unique_symbol` → `ls.request_implementing_symbols`; graceful error if LSP doesn't support it | `tool-contracts.json:get_implementations` |
| `get_docstring` | Hover text for a symbol | `resolve_unique_symbol` → `ls.request_hover`, text extraction | `tool-contracts.json:get_docstring` |
| `rename_symbol` | Rename across the project | `resolve_unique_symbol` → `ls.request_rename_symbol_edit` → `ls.apply_text_edits_to_file` | `tool-contracts.json:rename_symbol` |

---

## Key data directories

- **`.venv/`** — Package-local Python virtualenv with solidlsp dependencies (`sensai-utils`, `pathspec`, `jsonschema`, `pyyaml`). Created by `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
- **`.solidlsp/`** — SolidLSP cache directory (language server installs). Created automatically by SolidLSP on first start.

---

## Project configuration (`.serenaproject.yml`)

To configure per-project language server settings, place a `.serenaproject.yml` file in the **root of your project** (the `cwd` passed to the bridge).

On every `init`, the bridge reads this file for the `languages` list. Only the `languages` key is used by the current bridge — other keys are passed through to SolidLSP but their effect depends on the vendored SolidLSP version.

Example `.serenaproject.yml`:

```yaml
languages:
  - typescript
  - python
```

If no `.serenaproject.yml` is present, the bridge auto-detects the language from the project's file structure (TypeScript files → typescript, Python files → python, fallback to typescript).

---

## Build, test, and dev commands

```bash
# Install dependencies
npm install
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Type-check (TypeScript, noEmit)
npm run typecheck
# or: npx tsc -p tsconfig.json --noEmit

# Full regression test (typechecks + JSONL bridge test)
npm test

# Run regression test alone
npm run test:jsonl
# or: node --import @mariozechner/jiti/register scripts/jsonl-regression.ts

# Run pi with the extension (from a project root)
pi -e /path/to/pi-serena-lsp

# CLI — invoke LSP tools manually (debugging / exploration)
.venv/bin/python bridge/cli.py --help
.venv/bin/python bridge/cli.py -p ~/myproject find_symbol --name-path MyClass
.venv/bin/python bridge/cli.py -p ~/myproject get_document_overview --relative-path src/main.ts
```

The regression test (`scripts/jsonl-regression.ts`) creates temporary TypeScript and Python fixtures in `/tmp`, exercises every tool, and exits non-zero on failure.

### CLI reference (`bridge/cli.py`)

A standalone Python CLI for manual LSP tool invocation. Calls the `Bridge` class directly — no JSONL, no subprocess, no agent harness. Fast startup, native Python stack traces, easy to debug with `pdb`.

| Subcommand | Required args | Optional args |
|---|---|---|
| `find_symbol` | `--name-path` | `--relative-path`, `--code-snippet`, `--kinds`, `--max-matches` |
| `get_document_overview` | `--relative-path` | `--depth` |
| `get_document_symbols` | `--relative-path` | `--depth` |
| `get_type` | `--name-path` | `--relative-path` |
| `get_references` | `--name-path` | `--relative-path` |
| `get_implementations` | `--name-path` | `--relative-path` |
| `get_docstring` | `--name-path` | `--relative-path` |
| `rename_symbol` | `--name-path`, `--new-name` | `--relative-path` |

Global options: `-p/--project` (project root, default cwd), `--compact` (compact JSON output).

`--kinds` accepts LSP SymbolKind names: File, Module, Package, Class, Method, Function, Variable, Interface, Enum, Property, etc.

Ambiguous `name_path` resolutions print a candidate list to stderr with suggested refinements.

---

## Conventions and constraints

### API & schema

1. **`src/tool-contracts.json` is the single source of truth.** When adding or changing a tool parameter, always update this file first, then sync `src/schemas.ts` (TypeBox) and `bridge/serena_pi_bridge.py`. The two are intentionally kept separate so TypeScript can use TypeBox features that JSON Schema doesn't natively support.

2. **No diagnostics in v1.** Do not expose diagnostic tools (like `get_diagnostics_for_file`). The vendored SolidLSP does not provide stable cross-language diagnostic APIs.

3. **name_path pattern matching.** `find_symbol` uses `NamePathMatcher`: component-by-component, right-to-left, each component exact. A bare `send` matches any symbol whose last component is `send`. A full `/MyClass/send` requires exact full match. `resolve_unique_symbol` (used by all action tools) follows the same rules and raises `SymbolResolutionError` with candidates on ambiguity.

### Operational boundaries

1. **Bridge does not auto-register language servers.** The ADR at `docs/adr/0001-remove-bridge-language-detection.md` explains why. If an LSP call fails because a language isn't configured, the user/agent must configure it via `.serenaproject.yml` in the project root (see [Project configuration](#project-configuration-serenaprojectyml)).

2. **Per-cwd clients.** The extension keeps one `SerenaBridgeClient` per working directory. Switching projects kills the old Python process and spawns a new one. This means the SolidLSP state is scoped to one project at a time.

3. **Pass-through results.** Tool outputs are JSON from SolidLSP internals. They are not a stable structured API for non-agent consumers. The agent must parse and handle the raw shape.

### Error handling & isolation

1. **Ambiguity errors.** When `resolve_unique_symbol` finds multiple matches for a `name_path`, the bridge returns a `SymbolResolutionError` with a `candidates` list. The TypeScript extension catches these and returns `{error, candidates}` so the agent can refine via `find_symbol` first.

2. **Python environment is package-local.** The bridge uses `.venv/bin/python` — never the system Python. This avoids dependency conflicts with the user's project.

---

## Gotchas

- `rename_symbol` applies the rename immediately via LSP — it mutates files in the user's project. Use it only when the agent intends a real rename. The LSP may reject the request if the workspace has errors.
- `get_document_symbols` is deprecated — prefer `get_document_overview`, which also returns symbol line ranges and imports.
- `find_implementations` may fail with "not supported by the active language server" if the server doesn't support `textDocument/implementation`. This is handled gracefully.
- `relative_path` values are canonicalised by the bridge: converted to project-root-relative paths. If the path doesn't resolve, the tool will fail with a "File not found" error.
- `relative_path` is optional for all tools except `get_document_symbols` (which needs a file path). Omit it for project-wide search.
