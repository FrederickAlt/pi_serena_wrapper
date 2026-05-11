#!/usr/bin/env python3
"""CLI for manually invoking pi-serena-lsp tools against a project.

Directly calls the Bridge class — no JSONL, no subprocess, no agent harness.
Fast startup, native Python stack traces, easy to debug with pdb/print.

Usage:
    .venv/bin/python bridge/cli.py -p ~/myproject find_symbol --name-path MyClass
    .venv/bin/python bridge/cli.py -p ~/myproject get_references --name-path MyClass/myMethod
    .venv/bin/python bridge/cli.py -p ~/myproject get_document_overview --relative-path src/main.ts
    .venv/bin/python bridge/cli.py -p ~/myproject get_type --name-path User
    .venv/bin/python bridge/cli.py -p ~/myproject rename_symbol --name-path oldName --new-name newName
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

# Ensure vendored solidlsp is importable (same as serena_pi_bridge.py).
_BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

from serena_pi_bridge import Bridge, SymbolResolutionError


# ---------------------------------------------------------------------------
# SymbolKind names (for --kinds choices and help text)
# ---------------------------------------------------------------------------

from solidlsp.ls_types import SymbolKind

_KIND_NAMES = [k.name for k in SymbolKind]


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="serena-cli",
        description="Invoke Serena LSP tools directly from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s -p ~/myproject find_symbol --name-path MyClass
  %(prog)s -p ~/myproject find_symbol --name-path send --kinds Method Function
  %(prog)s -p ~/myproject get_references --name-path MyClass/myMethod
  %(prog)s -p ~/myproject get_document_overview --relative-path src/main.ts --depth 1
  %(prog)s -p ~/myproject get_type --name-path User
  %(prog)s -p ~/myproject get_docstring --name-path MyClass/myMethod
  %(prog)s -p ~/myproject get_implementations --name-path MyInterface
  %(prog)s -p ~/myproject rename_symbol --name-path oldName --new-name newName
""",
    )

    parser.add_argument(
        "-p", "--project",
        default=os.getcwd(),
        help="Project root directory (default: current working directory).",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Output compact JSON (no indentation).",
    )

    sub = parser.add_subparsers(dest="tool", required=True)

    # -- find_symbol --------------------------------------------------------

    find = sub.add_parser("find_symbol", help="Search the symbol tree by name path pattern.")
    find.add_argument("--name-path", required=True, help="Serena name path pattern.")
    find.add_argument("--relative-path", help="Scope search to a file or directory.")
    find.add_argument("--code-snippet", help="Exact code snippet to filter by (via rg).")
    find.add_argument("--kinds", nargs="*", choices=_KIND_NAMES, metavar="KIND",
                       help=f"Filter by LSP SymbolKind names: {', '.join(_KIND_NAMES)}")
    find.add_argument("--max-matches", type=int, default=10,
                      help="Max matches to return (-1 = unlimited). Default: 10.")

    # -- get_document_overview ----------------------------------------------

    overview = sub.add_parser("get_document_overview",
                              help="Two-section overview: Imports + Symbols with line ranges.")
    overview.add_argument("--relative-path", required=True,
                          help="Path to a source file, relative to project root.")
    overview.add_argument("--depth", type=int, default=0,
                          help="Descendant nesting depth for symbols. Default: 0.")

    # -- get_type -----------------------------------------------------------

    gtype = sub.add_parser("get_type", help="Resolve a name_path to its defining type.")
    gtype.add_argument("--name-path", required=True, help="Serena name path to resolve.")
    gtype.add_argument("--relative-path", help="Scope search to a file or directory.")

    # -- get_references -----------------------------------------------------

    refs = sub.add_parser("get_references", help="Find all references to a symbol.")
    refs.add_argument("--name-path", required=True, help="Serena name path.")
    refs.add_argument("--relative-path", help="Scope search to a file or directory.")

    # -- get_implementations ------------------------------------------------

    impls = sub.add_parser("get_implementations",
                           help="Find implementations of an interface/abstract symbol.")
    impls.add_argument("--name-path", required=True, help="Serena name path.")
    impls.add_argument("--relative-path", help="Scope search to a file or directory.")

    # -- get_docstring ------------------------------------------------------

    docs = sub.add_parser("get_docstring", help="Get hover text / documentation for a symbol.")
    docs.add_argument("--name-path", required=True, help="Serena name path.")
    docs.add_argument("--relative-path", help="Scope search to a file or directory.")

    # -- rename_symbol ------------------------------------------------------

    rename = sub.add_parser("rename_symbol",
                            help="Rename a symbol across the project (MUTATES FILES).")
    rename.add_argument("--name-path", required=True, help="Serena name path of the symbol to rename.")
    rename.add_argument("--new-name", required=True, help="New symbol name.")
    rename.add_argument("--relative-path", help="Scope search to a file or directory.")

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def args_to_params(args: argparse.Namespace) -> dict[str, object]:
    """Convert parsed argparse.Namespace to a params dict (with None values stripped)."""
    params: dict[str, object] = {}
    skip = {"tool", "project", "compact", "func"}
    for key, value in vars(args).items():
        if key in skip:
            continue
        # argparse sets unset optional args to None — strip them so the
        # bridge's validation doesn't choke on unexpected nulls.
        if value is not None:
            params[key.replace("_", "_")] = value
    return params


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    bridge = Bridge()

    try:
        # --- init ---
        project_root = os.path.abspath(args.project)
        print(f"Initializing language server for {project_root} ...", file=sys.stderr)
        init_result = bridge.init(project_root)
        print(f"→ language={init_result.get('language')}, cwd={init_result.get('cwd')}", file=sys.stderr)

        # --- call tool ---
        params = args_to_params(args)
        print(f"→ calling {args.tool} with {json.dumps(params, default=str)}", file=sys.stderr)
        result = bridge.call_tool(args.tool, params)

        # --- output ---
        indent = None if args.compact else 2
        print(json.dumps(result, indent=indent, ensure_ascii=False, default=str))

        # --- shutdown ---
        bridge.shutdown()
        return 0

    except SymbolResolutionError as exc:
        print(f"\nSymbolResolutionError: {exc}", file=sys.stderr)
        if exc.candidates:
            print("Candidates:", file=sys.stderr)
            for c in exc.candidates:
                print(f"  {c.get('name_path', '?')}  [{c.get('kind', '?')}]  {c.get('location', '?')}", file=sys.stderr)
        bridge.shutdown()
        return 1

    except Exception as exc:
        print(f"\nError: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        bridge.shutdown()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
