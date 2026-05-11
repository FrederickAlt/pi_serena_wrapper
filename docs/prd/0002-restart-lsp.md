# PRD: `restart_lsp` — Agent-driven LSP reload

## Problem Statement

When an agent uses the Serena LSP tools and the language server enters a bad state (stale index, crashed subprocess, resource exhaustion, or project config changes that require a re-index), the agent has no way to recover. It must wait for the session to end or for the human to intervene. The agent is stuck with a broken toolchain it cannot fix itself.

## Solution

Expose a new `restart_lsp` tool that the agent can call to kill the current language server process(es) and restart them fresh. The tool takes the project `cwd` as a required parameter and returns the same initialization confirmation payload as a normal bridge init — languages active, config values, project root. After a successful restart, all seven LSP tools work again against the freshly-indexed project.

## User Stories

1. As an agent, I want to restart the LSP when tools start returning stale or incorrect symbol results, so that I can self-heal without human intervention.
2. As an agent, I want to restart the LSP after editing `.serenaproject.yml` to pick up language configuration changes, so that my config edits take effect immediately.
3. As an agent, I want to restart the LSP when the bridge process crashes or times out, so that I can recover and continue my task.
4. As an agent, I want to receive the same initialization payload after a restart that I would after a fresh session start, so that I can confirm the LSP restarted correctly and inspect the new state.
5. As an agent, I want the restart to be a full clean-slate operation — kill everything and start fresh — so that I don't carry forward any corrupt state.
6. As an agent, I want to pass the project root (`cwd`) explicitly as a required parameter, so that the restart is unambiguous even if the bridge lost track of its working directory.
7. As an agent, I want in-flight tool calls to be rejected with clear errors during a restart, so that I know which operations need to be retried.
8. As an agent working with a multi-language project, I want all configured language servers (TypeScript, Python, etc.) to be restarted together, so that I get a consistent clean slate across languages.

## Implementation Decisions

### Tool contract

- **Tool name**: `restart_lsp`
- **Parameters**: `cwd` (string, required) — project root directory
- **Returns**: Same init confirmation payload as a fresh bridge init — `ok`, `language`, `languages`, `exclude_dot_paths`, `document_overview_default_kinds`, `cwd`

### Architecture — TypeScript-side execution

Unlike the other seven tools (which dispatch through the Python bridge via `call_tool`), `restart_lsp` **cannot cross the bridge** because the tool kills the process that would handle the request. The execute handler calls the bridge client directly in TypeScript, bypassing the JSON-RPC transport entirely.

The `SerenaBridgeClient` gains a `restart(cwd)` method that:

1. Calls `shutdown()` — kills the current Python subprocess (force-kills after a grace period if the process hangs)
2. Calls `init(cwd)` — spawns a new Python subprocess, sends the `init` RPC, returns the confirmation payload

The tool registration in the extension's execute handler calls `clientFor().restart(params.cwd)` directly — no `callTool`, no `wrapAmbiguity`.

### In-flight request behavior

When `shutdown()` kills the subprocess, the transport's `exit` handler auto-rejects all pending promises with a "bridge exited" error. No special coordination is needed — in-flight calls fail, the agent retries after restart.

### Error handling

- **Shutdown failure**: force-kill after a short grace period, then proceed to init. The old process must not block the restart.
- **Init failure**: reject the tool call with the init error. The agent receives the error and decides how to proceed (fix config, retry, etc.).
- **Never initialized**: if the bridge was never started (no prior `init`), `restart` attempts a fresh init with the given `cwd`. The agent gets a clean start.

### Files modified

Four existing files are modified; no new modules are created:

- **Tool contracts** — Add `restart_lsp` entry with `cwd` (required string) parameter schema
- **TypeBox schemas** — Add `restart_lsp` TypeBox schema and wire up the description from the contract
- **Bridge client** — Add `restart(cwd)` method composing existing `shutdown()` + `init(cwd)`
- **Extension registration** — Register `restart_lsp` tool with a direct execute handler (no bridge dispatch, no ambiguity wrapper)

The Python bridge is not modified. No new `call_tool` dispatch path is needed.

### Agent prompt guidelines

No prompt guidelines are registered. The tool name and description are self-explanatory.

## Testing Decisions

### What makes a good test

Test external behavior: call restart, observe that subsequent LSP tool calls succeed against a freshly-indexed project. Do not test internal transport mechanics (subprocess spawning, pipe handling).

### Modules tested

The existing integration regression suite (`jsonl-regression.ts`) is extended with a restart cycle test:

1. Call `find_symbol` — confirm it works before restart
2. Call `restart_lsp` — confirm it returns the init confirmation payload
3. Call `find_symbol` again — confirm it still works after restart

No unit tests are needed because `restart(cwd)` is a composition of two already-tested methods (`shutdown()` and `init(cwd)`) with no new logic.

### Prior art

`scripts/jsonl-regression.ts` — end-to-end regression test that exercises every tool against temporary TypeScript and Python fixtures. The restart test follows the same pattern: create fixtures, test before, restart, test after.

## Out of Scope

- Per-language restart (restarting only TypeScript but keeping Python running). The tool restarts all configured language servers.
- Restart without a `cwd` parameter. The parameter is always required.
- Automatic restart on bridge crash. This is an agent-invoked tool, not an auto-recovery mechanism.
- Configuration changes bundled into the restart call. The agent edits `.serenaproject.yml` separately, then calls `restart_lsp` to pick up changes.
- Restart progress streaming or intermediate status updates. The tool returns a single final confirmation.

## Further Notes

- The `init` path already handles project switching gracefully — if the agent passes a different `cwd` than the current project, the bridge re-inits for the new project. This is existing behavior exposed through the new tool name.
- The force-kill-on-shutdown-hang behavior is an extension of the transport's existing timeout handling, which already kills the process on request timeout.
