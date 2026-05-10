# agent.md — pi-serena-lsp

## What this is

A **pi extension** that exposes Serena's symbolic LSP backend as pi tools. When the pi harness loads this extension, it registers 7 tools (`get_symbols_overview`, `find_symbol`, `get_symbol_from_snippet`, `find_referencing_symbols`, `find_declaration`, `find_implementations`, `rename_symbol`) that let an agent query Serena's project index through language servers.

The extension is a thin bridge between two runtimes: the pi agent (Node.js/TypeScript) and Serena (Python). The Node side registers tools, manages per-project bridge clients, and sends JSON-RPC requests over stdin/stdout to a Python subprocess that wraps `SerenaAgent`.

---

## Repository layout

```
pi-serena-lsp/
├── src/                        # TypeScript — pi extension
│   ├── extension.ts            # Entry point: registers 7 tools, manages clients
│   ├── schemas.ts              # TypeBox parameter schemas (synced with tool-contracts.json)
│   ├── bridge-client.ts        # Node JSONL client: spawns Python bridge, sends requests
│   └── transport.ts            # JSON-RPC transport via subprocess stdin/stdout
├── bridge/                     # Python — Serena bridge backend
│   ├── serena_pi_bridge.py     # JSONL server: validates Serena, routes tool calls to SerenaAgent
│   └── source_positions.py     # Source position resolution for get_symbol_from_snippet
├── scripts/
│   └── jsonl-regression.ts     # Regression test — exercises every tool against TS/Python fixtures
├── docs/
│   └── adr/                    # Design decisions made
│       └── 0001-remove-bridge-language-detection.md  
├── tool-contracts.json         # Shared JSON schema — single source of truth for tool params
├── package.json                # pi extension manifest (pi.extensions → src/extension.ts)
├── tsconfig.json               # TypeScript config (noEmit, type-check only)
└── requirements.txt            # Python deps (sensai-utils + pathspec + jsonschema + pyyaml)
```

## Serena Repo

This is located at `../serena/`. You should only read this and not edit! The docs are in `../serena/docs` and the source is at `../serena/src`.

## Architecture

```
pi harness (Node/TS)  ──JSONL over stdin/stdout──►  serena_pi_bridge.py (Python)
                                                           │
                                                           ▼
                                                     SerenaAgent + SolidLSP
```

- **`src/extension.ts`** — Loaded by pi at startup. Calls `pi.registerTool()` for each of the 7 tool names. Maintains one `SerenaBridgeClient` instance; on `session_shutdown` it kills the Python process.
- **`src/bridge-client.ts`** — Spawns `bridge/serena_pi_bridge.py` via the local `.venv` Python. Sends `init`, `call_tool`, `shutdown` commands. Handles retry on Serena version mismatch (reinstalls `serena-agent`). Tracks the current `cwd` so switching projects re-inits Serena.
- **`src/transport.ts`** — `SubprocessTransport` class: spawns the Python process, reads JSONL from stdout, writes to stdin. Handles timeouts (default 240s), abort signals, and stderr capture.
- **`bridge/serena_pi_bridge.py`** — `Bridge` class: validates the Serena install on `init`, creates a `SerenaAgent` with LSP backend. Routes each tool call to the appropriate Serena/SolidLSP API. Validates arguments against `tool-contracts.json` before dispatch. Logs failures to `.serena-data/failed-tool-calls.jsonl`.
- **`bridge/source_positions.py`** — Given a file's full content, a `code_snippet`, and a `symbol_text`, finds all occurrences and resolves (line, column) positions. Used by `get_symbol_from_snippet`.
- **`tool-contracts.json`** — The canonical parameter definitions. **Both `schemas.ts` and `serena_pi_bridge.py` derive from this file.** If you add or change a tool parameter, update this file first, then sync the TypeBox and Python validation.

---

## 7 tools and where they live

| Tool | Responsibility | Dispatch in bridge | Relevant contract |
|---|---|---|---|
| `get_symbols_overview` | Top-level symbols in a file | `agent.get_tool_by_name("get_symbols_overview").apply_ex(...)` | `tool-contracts.json:get_symbols_overview` |
| `find_symbol` | Exact symbol lookup by `name_path` | `agent.get_tool_by_name("find_symbol").apply_ex(...)` with post-processing | `tool-contracts.json:find_symbol` |
| `get_symbol_from_snippet` | Resolve source snippet → symbol | Calls `source_positions.py`, then SolidLSP `request_defining_symbol` / `request_type_definition` | `tool-contracts.json:get_symbol_from_snippet` |
| `find_referencing_symbols` | Find all references to a symbol | Uses `SymbolRetriever.find_referencing_symbols_by_location`, groups by file | `tool-contracts.json:find_referencing_symbols` |
| `find_declaration` | Go to declaration/definition | SolidLSP `request_defining_symbol` / `request_definition` | `tool-contracts.json:find_declaration` |
| `find_implementations` | Find interface/abstract implementations | SolidLSP `request_implementing_symbols`; catches unsupported LSP methods gracefully | `tool-contracts.json:find_implementations` |
| `rename_symbol` | Rename across the project | `LanguageServerCodeEditor.rename_symbol` (Serena's code_editor module) | `tool-contracts.json:rename_symbol` |

---

## Key data directories

- **`.venv/`** — Package-local Python virtualenv with vendored solidlsp dependencies (`sensai-utils`, `pathspec`, `jsonschema`, `pyyaml`). Created by `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
- **`.serena-data/`** — Serena home directory: language server installs, memories, prompt templates. Also contains `failed-tool-calls.jsonl` — log of every failed tool invocation (timestamp, args, error).
- **`.serena-projects/`** — Per-project Serena metadata, keyed by `<folder-name>-<sha256-prefix>`. The bridge stores project data here so Serena doesn't pollute the user's project.

---

## Project configuration (`.serenaproject.yml`)

To configure per-project Serena settings (most importantly, the list of active language servers), place a `.serenaproject.yml` file in the **root of your project** (the `cwd` passed to the bridge).

On every `init`, the bridge reads this file and:

1. **Writes it to `project.local.yml`** inside the project's `.serena-projects/<hash>/` directory.
2. On first init for a project, the bridge also creates a minimal `project.yml` stub so that Serena's config loader merges the local overrides natively instead of auto-generating and discarding them.
3. All settings (including `languages`, `encoding`, `ignored_paths`, etc.) are applied **immediately** — Serena reads the merged config during agent initialisation. No two-phase patching, no "takes effect next session".

Example `.serenaproject.yml`:

```yaml
# List of language servers to activate (see project.yml for the full enum)
languages:
  - typescript
  - python

# Optional: encoding used by source files in the project
encoding: "utf-8"

# Optional: additional paths to ignore (gitignore syntax)
ignored_paths:
  - "**/generated/**"
  - "**/vendor/**"
```

Recognised keys: `languages`, `encoding`, `ignore_all_files_in_gitignore`, `ignored_paths`, `ls_specific_settings`, `read_only`, `excluded_tools`, `included_optional_tools`, `fixed_tools`, `base_modes`, `default_modes`, `initial_prompt`, `symbol_info_budget`, `line_ending`, `read_only_memory_patterns`, `ignored_memory_patterns`.

Unknown keys generate a warning on stderr but are not blocking.

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
```

The regression test (`scripts/jsonl-regression.ts`) creates temporary TypeScript and Python fixtures in `/tmp`, exercises every tool, and exits non-zero on failure. It also verifies that removed tools (`get_diagnostics_for_file`, `get_diagnostics_for_symbol`, `find_type_definition`) are rejected.

---

## Conventions and constraints

### API & schema

1. **`tool-contracts.json` is the single source of truth.** When adding or changing a tool parameter, always update this file first, then sync `src/schemas.ts` (TypeBox) and `bridge/serena_pi_bridge.py::validate_args()`. The two are intentionally kept separate so TypeScript can use TypeBox features (e.g. `Type.Union`) that JSON Schema doesn't natively support.

2. **No diagnostics in v1.** Do not expose `get_diagnostics_for_file` or `get_diagnostics_for_symbol`. The vendored Serena tool registry doesn't provide stable diagnostic tools, and the bridge should not present ad-hoc compiler-specific fallbacks as a cross-language API.

3. **Exact name_path matching only.** `find_symbol` uses exact `name_path` lookup. Do not mix fuzzy/substring search into the same tool. Substring matching is controlled by Serena internals and should stay separate.

### Operational boundaries

1. **Bridge does not auto-register language servers.** The ADR at `docs/adr/0001-remove-bridge-language-detection.md` explains why. If an LSP call fails because a language isn't configured, the user/agent must configure it via `.serenaproject.yml` in the project root (see [Project configuration](#project-configuration-serenaprojectyml)).

2. **Per-cwd clients.** The extension keeps one `SerenaBridgeClient` per working directory. Switching projects kills the old Python process and spawns a new one. This means Serena state (index, language servers) is scoped to one project at a time.

3. **Pass-through results.** Tool outputs are JSON from Serena/SolidLSP internals. They are not a stable structured API for non-agent consumers. The agent must parse and handle the raw shape.

### Error handling & isolation

1. **Failed tool call logging.** All 7 tools log failures to `.serena-data/failed-tool-calls.jsonl`. The log records timestamp, cwd, tool name, args, failure kind, and error message. `find_implementations` on an unsupported language server is logged as an error_result, not an exception.

2. **Python environment is package-local.** The bridge uses `.venv/bin/python` — never the system Python or a globally installed Serena. This avoids dependency conflicts with the user's project.

---

## Gotchas

- `rename_symbol` applies the rename immediately via LSP — it mutates files in the user's project. Use it only when the agent intends a real rename. The LSP may reject the request if the workspace has errors.
- `find_implementations` may fail with "not supported by the active language server" if the server doesn't support `textDocument/implementation`. This is handled gracefully and logged as a failed tool call.
- `get_symbol_from_snippet` may return `unresolved` with `locations` if the LSP resolves the occurrence but it cannot be converted to a Serena project symbol (e.g. external dependency). The agent should fall back to inspecting the raw locations.
- The bridge stores Serena project data in `.serena-projects/` keyed by a hash of the absolute project path, not the folder name. This prevents collisions but means stale entries accumulate.
- `relative_path` values you pass to tools are canonicalised by the bridge before reaching the LSP: it converts them to project-root-relative paths and checks that the file exists on disk. If the path doesn't resolve to a real file, the tool will fail with a "File not found" error, even if the LSP could theoretically handle it.
