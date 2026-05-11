### What's already deep

 Two modules already have the shape the skill promotes — small interface, large implementation:

- name_path.py — compute_name_path, NamePathMatcher, resolve_unique_symbol, resolve_unique_symbol_via_workspace, SymbolResolutionError. One module, high leverage.
 Callers get symbol resolution across language servers with ambiguity reporting. Tests exist at bridge/test_name_path.py.
- import_parser.py — parse_imports(source_code, language) returning triples. Complex tree-sitter implementation behind one function. Clear seam at the language
 identifier — adding a new language means extending this module, not touching callers.

### Where the friction is

 The friction centers on the Bridge class (bridge/serena_pi_bridge.py, ~1470 lines). It mixes these concerns into one module:

 ┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┬─────────────────┐
 │ Concern                                                                                                               │ Lines (approx.) │
 ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
 │ LSP lifecycle (init, shutdown, per-language server map)                                                               │ ~120            │
 ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
 │ JSONL main loop (main(), respond())                                                                                   │ ~60             │
 ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
 │ Tool dispatch (call_tool if/elif chain)                                                                               │ ~30             │
 ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
 │ 7 tool implementations                                                                                                │ ~1050           │
 ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
 │ Import classification (_classify_import,_resolve_import_location, _verify_module_file_match)                         │ ~180            │
 ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
 │ Config (_read_languages, _write_languages, _detect_languages, _read_exclude_dot_paths, _read_document_overview_kinds) │ ~90             │
 ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
 │ rg snippet filtering (_filter_by_snippet)                                                                             │ ~60             │
 ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
 │ Tree flattening, kind parsing, symbol formatting                                                                      │ ~50             │
 ├───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
 │ Language dispatch (_ls_for_file, _ls_list_for,_language_for_file, _start_language_lazily)                            │ ~60             │
 └───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴─────────────────┘

 ────────────────────────────────────────────────────────────────────────────────

 Deepening candidates

### 1. Extract an import resolution module from the Bridge

- Files: bridge/serena_pi_bridge.py (methods _classify_import, _resolve_import_location,_verify_module_file_match,_resolve_python_module), possibly new file
 bridge/import_resolver.py
- Problem: ~180 lines of import classification live on the Bridge class but don't need the full Bridge state. They need a SolidLanguageServer, a file path, and
 resolve_unique_symbol_via_workspace. The deletion test: if you move them, the Bridge loses ~180 lines and gains a call to resolve_imports(import_pairs, file_path, ls).
 The complexity reappears in the new module, but with locality — all import classification logic in one place, testable without a full Bridge.
- Solution: Pull _classify_import, _resolve_import_location,_verify_module_file_match, and_resolve_python_module into bridge/import_resolver.py. The interface would be
 a single function: classify_imports(import_pairs, file_path, ls) -> list[ClassifiedImport]. The _get_document_overview method calls it.
- Benefits: Locality — import classification tests no longer need a full Bridge init cycle. Leverage — the one entry point serves every caller that needs to classify
 imports (currently only _get_document_overview, but the pattern is reusable). The Bridge shrinks by ~180 lines.

### 3. Extract a shared "symbol resolution + position extraction" helper

- Files: bridge/serena_pi_bridge.py (6 tool methods that repeat resolution logic), possibly new file bridge/resolution.py
- Problem: Every action tool (get_type, get_references, get_implementations, get_docstring, rename_symbol) does this exact dance:
     1. Parse name_path from params, validate non-empty
     2. Extract optional relative_path from params
     3. Call _ls_list_for(relative_path) → resolve_unique_symbol_via_workspace(ls_list, name_path, relative_path)
     4. Extract selectionRange / range, line, column from the resolved symbol
     5. Extract relativePath from location
 This is ~15 lines repeated 5 times.
- Solution: A resolve_tool_symbol(params, ls_map, cwd) function that takes raw params and the server map and returns a ResolvedSymbol named tuple with (symbol,
 file_path, line, column, ls_instance). Each tool calls this once and gets everything it needs.
- Benefits: Locality — changes to how resolution works (e.g., switching from resolve_unique_symbol_via_workspace to something else) happen in one place. Currently each
 tool would need updating individually. Leverage — the helper has one clear contract: "given tool params, give me the resolved symbol with all position info." Tool
 implementations get shorter and more focused.

### 4. Data-driven tool dispatch instead of if/elif

- Files: bridge/serena_pi_bridge.py (call_tool), src/extension.ts (7 pi.registerTool calls)
- Problem: The call_tool method uses an if/elif chain. The TypeScript extension.ts has 7 nearly identical pi.registerTool() calls, each with an inline execute function
 that differs only by tool name string. Adding an 8th tool requires touching 6 places (tool-contracts.json, schemas.ts, Python dispatch, Python implementation,
 extension.ts registerTool + guidelines). This is fragile.
- Solution: On the Python side, register tools in a dict: {"find_symbol": find_symbol_tool, ...} and dispatch with self._tools[tool_name](params). On the TypeScript
 side, derive pi.registerTool calls from a shared tool registry — a loop over a TOOLS array that contains name, schema, description, and guidelines.
- Benefits: Locality — adding a tool means one dict entry on the Python side, one array entry on the TS side. Leverage — the dispatch pattern is defined once, used
 everywhere. Currently the 7 registerTool calls in extension.ts differ only by tool name and guidelines string — those differences should be data, not code paths.
 Contradicts ADR-0001 only in spirit — the ADR is about import extraction, not dispatch mechanism — no conflict.

### 6. The tool-contracts.json → schemas.ts sync is a drag

- Files: src/tool-contracts.json, src/schemas.ts
- Problem: tool-contracts.json is the SSOT, but schemas.ts must be manually kept in sync because TypeBox features (Type.Union, Type.Optional) don't translate 1:1 to JSON
 Schema. The current approach — loading the JSON at runtime for descriptions but defining schemas separately — means half the description lives in JSON and half in
 TypeBox description fields. When you add a parameter, you touch both files and hope they match.
- Solution: Generate schemas.ts (or at least the TypeBox parts) from tool-contracts.json at build time, or generate tool-contracts.json from schemas.ts as the SSOT.
 TypeScript already has createRequire loading the JSON at runtime for descriptions — the schemas could be generated instead of duplicated. A quick npm run sync-contracts
 script would suffice.
- Benefits: Locality — one file is the source of truth. No risk of drift. The current setup already fails gracefully (Python validates against the JSON, TypeScript
 defines types independently), but a mismatch between them would produce confusing runtime errors. This is a process/quality improvement, not architectural — lower
 priority.
