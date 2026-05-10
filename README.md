# pi Serena LSP

Standalone pi package exposing a SolidLSP-backed symbolic LSP tool set.

## Tools

V1 exposes seven tools:

- `find_symbol`
- `get_document_symbols`
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

## Regression Test

Run the direct JSONL bridge regression:

```sh
cd /home/frederick/projects/AI/pi_extensions/lsp/pi-serena-lsp
npm run test:jsonl
```

The script creates temporary TypeScript and Python fixtures, exercises each of the 7 tools, verifies removed tools are rejected, and exits non-zero on failure.

## Result Shapes

Tool results are agent-facing pass-through text/JSON from SolidLSP internals. They are not yet a stable structured API for non-agent consumers.
