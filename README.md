# pi Serena LSP

Standalone pi package exposing a SolidLSP-backed symbolic LSP tool set.

## Tools

V1 exposes seven tools:

- `find_symbol`
- `get_document_overview`
- `get_type`
- `get_references`
- `get_implementations`
- `get_docstring`
- `rename_symbol`

Diagnostics are intentionally not exposed in v1. The vendored SolidLSP does not provide stable cross-language diagnostic APIs, and the wrapper should not present ad-hoc compiler or language-specific fallbacks as a stable cross-language API.

## Setup

Create the package-local Python environment:

```sh
cd /home/frederick/projects/AI/pi_extensions/lsp/pi-serena-lsp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The bridge imports SolidLSP from the vendored `bridge/solidlsp/` directory. It does not depend on `serena-agent` or any external Serena installation.

Language server prerequisites are the responsibility of the user/system environment. The bridge does not install language servers, edit shell startup files, or modify `PATH`.

### Runtime dependencies

The `code_snippet` parameter of `find_symbol` relies on **ripgrep** (`rg`) to scope results by source text. If `rg` is not installed, `find_symbol` calls with `code_snippet` will fail with a `RuntimeError`. Install it via your system package manager:

- Debian/Ubuntu: `sudo apt install ripgrep`
- macOS: `brew install ripgrep`
- Arch: `sudo pacman -S ripgrep`

`find_symbol` without `code_snippet` does not require `rg`.

Examples:

- TypeScript projects require `node` and the TypeScript language server (auto-installed by SolidLSP).
- Python projects require `python` and Pyright (auto-installed by SolidLSP).
- Other languages require the language server expected by SolidLSP to be installed or otherwise available.

## Usage

Run pi with the extension from a project root:

```sh
pi -e /home/frederick/projects/AI/pi_extensions/lsp/pi-serena-lsp
```

The bridge stores SolidLSP data under `.solidlsp/` in the package directory.

## Multi-language configuration

Configuring multiple languages in `.serenaproject.yml` starts one language server per language, which increases memory usage. For example, a project with both TypeScript and Python configured will run two language server processes (typically ~200-400 MB each).

A language server is started lazily the first time a file of that language is accessed. To disable lazy loading and start all servers eagerly at init, explicitly list all needed languages in `.serenaproject.yml`.

### `exclude_dot_paths`

Set `exclude_dot_paths: false` in `.serenaproject.yml` to include symbols from dot-prefixed directories (`.venv`, `.git`, `.sandcastle`, etc.) in `find_symbol` and workspace symbol search results. Default is `true` (exclude).

Example:
```yaml
languages:
  - typescript
  - python
exclude_dot_paths: false
```

## Regression Test

Run the direct JSONL bridge regression:

```sh
cd /home/frederick/projects/AI/pi_extensions/lsp/pi-serena-lsp
npm run test:jsonl
```

The script creates temporary TypeScript and Python fixtures, exercises each of the 7 tools, verifies removed tools are rejected, and exits non-zero on failure.

## Result Shapes

Tool results are agent-facing pass-through text/JSON from SolidLSP internals. They are not yet a stable structured API for non-agent consumers.
