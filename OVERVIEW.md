# pi-serena-lsp — Overview

## What it is

A **pi extension** that exposes Serena's symbolic LSP backend as pi tools.

Serena indexes your project's source code through language servers (e.g. Pyright for TypeScript/Python). This extension lets pi query that index to inspect symbols, find declarations, track references, and refactor — directly from the agent loop.

## Architecture

```
┌─────────────┐     JSONL over stdin/stdout     ┌────────────────────┐
│  pi harness │ ◄──────────────────────────────► │  serena_pi_bridge  │
│  (Node/TS)  │                                  │  (Python)          │
└─────────────┘                                  └────────────────────┘
                                                          │
                                                          ▼
                                                  ┌──────────────┐
                                                  │ SerenaAgent  │
                                                  │ + SolidLSP   │
                                                  └──────────────┘
```

- **`src/extension.ts`** — Pi extension entry point. Registers 7 tools, manages per-cwd bridge clients, handles abort signals.
- **`src/schemas.ts`** — TypeBox parameter schemas and descriptions for each tool.
- **`src/bridge-client.ts`** — Node JSONL client. Spawns the Python bridge, sends requests, handles timeouts and retries.
- **`bridge/serena_pi_bridge.py`** — Python JSONL server. Validates Serena install, initializes `SerenaAgent`, routes tool calls.

## Exposed tools

| Tool | Purpose |
|------|---------|
| `get_symbols_overview` | Top-level symbols in a file |
| `find_symbol` | Exact lookup by `name_path` |
| `get_symbol_from_snippet` | Resolve a source snippet to a symbol |
| `find_referencing_symbols` | Find references to a symbol |
| `find_declaration` | Go to declaration/definition |
| `find_implementations` | Find implementations (LSP-dependent) |
| `rename_symbol` | Rename across the project |

## Data & state

- **`.serena-data/`** — Serena home. Contains failed-tool-call logs.
- **`.serena-projects/`** — Per-project metadata, keyed by a hash of the absolute project path.
- **`.venv/`** — Package-local Python environment with `serena-agent` installed.

## Key design decisions

1. **Per-cwd clients.** The extension maintains one `SerenaBridgeClient` per working directory. Switching projects creates a fresh Serena agent instance.
2. **No diagnostics in v1.** The vendored Serena registry doesn't expose stable diagnostic tools, so the extension doesn't either.
3. **Pass-through results.** Tool outputs are agent-facing JSON from Serena/SolidLSP. They are not yet a stable structured API for non-agent consumers.
4. **Exact matching by default.** `find_symbol` uses exact `name_path` matching. Fuzzy search is intentionally not mixed into the same tool.
