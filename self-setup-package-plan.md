# Make pi-serena-lsp Self-Setting-Up

## Summary

Make the extension usable with `pi install` / `pi -e` without manual Node or Python setup. The extension will declare its own Node dependencies, typecheck locally, and lazily create its package-local Python `.venv` for `serena-agent` on first use. It will not install language servers such as `gopls`; those remain explicit system prerequisites.

## Key Changes

- Add a real standalone pi package manifest.
  - Create `package.json` with `type: "module"` and `pi.extensions: ["./src/extension.ts"]`.
  - Add `@sinclair/typebox` as a runtime dependency.
  - Add `@mariozechner/pi-coding-agent`, `typescript`, and `@types/node` as dev/peer deps following the existing `pi-hooks` pattern.
  - Add scripts: `typecheck`, `test:jsonl`, and `test`.
- Switch schema import from:
  ```ts
  import { Type } from "typebox";
  ```
  to:
  ```ts
  import { Type } from "@sinclair/typebox";
  ```
- Add `tsconfig.json`.
  - Use `module: "NodeNext"`, `moduleResolution: "NodeNext"`, `strict: true`, `noEmit: true`.
  - Include `src/**/*.ts`.
- Add package-local Python bootstrap in `src/bridge-client.ts`.
  - If `.venv/bin/python` is missing, run:
    ```sh
    python3 -m venv .venv
    .venv/bin/pip install --upgrade -r requirements.txt
    ```
  - If bridge `init` reports missing/incompatible `serena-agent`, run the pip install once and retry.
  - Keep setup under the extension directory only; never create `.venv` in the user project cwd.
- Keep language servers external.
  - Do not auto-install `go`, `gopls`, Node language servers, or project dependencies.
  - If Serena/SolidLSP reports a missing language server, surface the message clearly.

## Behavior

- First tool call may take longer while `.venv` is created and `serena-agent` is installed.
- Subsequent calls reuse the package-local `.venv`.
- If Python, venv creation, or pip install fails, the tool error should include the command that failed and the captured stderr.
- User project directories stay clean. Extension-owned files remain under:
  ```text
  pi-serena-lsp/.venv
  pi-serena-lsp/.serena-data
  pi-serena-lsp/.serena-projects
  pi-serena-lsp/node_modules
  ```

## Test Plan

- Node/package setup:
  ```sh
  npm install
  npm run typecheck
  ```
- Python bootstrap from scratch:
  ```sh
  mv .venv .venv.bak
  npm run test:jsonl
  ```
  Confirm `.venv` is recreated under `pi-serena-lsp/.venv`.
- Existing bridge regression:
  ```sh
  node scripts/jsonl-regression.mjs
  ```
- Pi smoke:
  ```sh
  pi -e /home/frederick/projects/AI/pi_extensions/lsp/pi-serena-lsp
  ```
  Confirm all seven tools are visible.
- Failure-path smoke:
  - Temporarily break `requirements.txt` or Python path in a controlled test and verify the error is clear.
  - Run on a project missing a language server and verify the extension reports the missing external prerequisite instead of trying to install it.

## Assumptions

- `pi install` installs Node dependencies from `package.json`, matching existing pi package behavior.
- Auto-installing `serena-agent` inside the extension-owned `.venv` is acceptable.
- Auto-installing system language servers is intentionally out of scope.
