# pi Serena LSP

Standalone pi package exposing a small Serena-backed symbolic LSP tool set.

## Tools

V1 exposes seven tools:

- `get_symbols_overview`
- `find_symbol`
- `find_referencing_symbols`
- `find_declaration`
- `find_type_definition`
- `find_implementations`
- `rename_symbol`

Diagnostics are intentionally not exposed in v1. The vendored Serena tool registry does not provide native `get_diagnostics_for_file` or `get_diagnostics_for_symbol` tools, and the wrapper should not present ad-hoc compiler or language-specific fallbacks as a stable cross-language API.

## Setup

Create the package-local Python environment:

```sh
cd /home/frederick/projects/AI/pi_extensions/lsp/pi-serena-lsp
python3 -m venv .venv
.venv/bin/pip install --upgrade serena-agent
```

Equivalent requirements-file setup:

```sh
.venv/bin/pip install -r requirements.txt
```

The bridge imports Serena from the package-local Python environment. It does not
load Serena from a local source checkout or `vendor/serena`.

Language server prerequisites are the responsibility of the user/system environment. The bridge does not install language servers, edit shell startup files, or modify `PATH`.

Examples:

- Go projects require `go` and `gopls` on `PATH`.
- Other languages require the language server expected by Serena/SolidLSP to be installed or otherwise available to Serena.

## Usage

Run pi with the extension from a project root:

```sh
pi -e /home/frederick/projects/AI/pi_extensions/lsp/pi-serena-lsp
```

The bridge stores Serena data under the package directory and keys project metadata by a hash of the absolute project path. Older non-hashed `.serena-projects/<folder-name>` metadata can be removed manually if it is no longer needed.

## Regression Test

Run the direct JSONL bridge regression:

```sh
cd /home/frederick/projects/AI/pi_extensions/lsp/pi-serena-lsp
node scripts/jsonl-regression.mjs
```

The script creates a temporary TypeScript fixture, verifies the six-tool public contract, confirms diagnostics tools are rejected, exercises each exposed tool once, and exits non-zero on failure.

## Failed Tool Log

Failed calls to the seven Serena tools are appended as JSONL here:

```text
.serena-data/failed-tool-calls.jsonl
```

The logger records only this package's Serena tool calls. It does not record built-in pi tools such as `bash`, `read`, `edit`, or user shell commands. Each entry includes timestamp, project cwd, tool name, arguments, failure kind, and error message. Unsupported language-server capabilities, such as `find_implementations` on a server that does not support `textDocument/implementation`, are logged as unsuccessful extension tool calls.

## Result Shapes

Tool results are agent-facing pass-through text/JSON from Serena or Serena/SolidLSP internals. They are not yet a stable structured API for non-agent consumers.
