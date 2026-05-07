# New pi-serena-lsp Interface And Returns

This document describes the intended public interface after the planned cleanup.

The extension would expose 7 tools:

- `get_symbols_overview`
- `find_symbol`
- `get_symbol_from_snippet`
- `find_referencing_symbols`
- `find_declaration`
- `find_implementations`
- `rename_symbol`

Diagnostics tools are not exposed.

## Design Rules

- Serena-native tools stay in Serena's symbol universe: `relative_path + name_path`.
- Source text targeting is isolated to `get_symbol_from_snippet`.
- No public tool accepts line/column.
- No public read tool returns source bodies.
- No public tool accepts `code_snippet`, `symbol_text`, `occurrence_index`, or `regex` except `get_symbol_from_snippet`.
- `body_location` means line range only; it is not source content.

## Common Types

```ts
type BodyLocation = {
  start_line: number | null;
  end_line: number | null;
};

type SerenaSymbolReference = {
  name_path: string;
  kind: string;
  relative_path: string | null;
  body_location?: BodyLocation;
};

type SerenaChildSymbol = {
  name?: string;
  kind?: string;
  body_location?: BodyLocation;
  children?: Record<string, string[] | SerenaChildSymbol[]>;
};

type LspLocation = {
  relativePath?: string;
  uri?: string;
  range: {
    start: {
      line: number;
      character: number;
    };
    end: {
      line: number;
      character: number;
    };
  };
};
```

Note for prompt/system text: `kinds` uses standard LSP `SymbolKind` integer values.

## get_symbols_overview

Gets a compact Serena symbol overview for one source file.

### Input Schema

```ts
type GetSymbolsOverviewInput = {
  relative_path: string;
  depth?: number;
};
```

### Return Schema

Serena compact overview grouped by kind.

```ts
type GetSymbolsOverviewOutput = Record<
  string,
  string[] | OverviewSymbol[] | Record<string, unknown>
>;

type OverviewSymbol = {
  name?: string;
  kind?: string;
  children?: Record<string, string[] | OverviewSymbol[]>;
};
```

Typical `depth: 0` output:

```json
{
  "Class": ["SerenaBridgeClient"],
  "Function": ["normalizeExecuteArgs"]
}
```

`children` is only expected when `depth >= 1` and the language server reports child symbols.

## find_symbol

Searches Serena's symbol index by name path pattern.

### Input Schema

```ts
type FindSymbolInput = {
  name_path_pattern: string;
  relative_path?: string;
  depth?: number;
  kinds?: number[];
  max_matches?: number;
};
```

Hardcoded internally:

```ts
include_body = false;
include_info = false;
exclude_kinds = [];
substring_matching = false;
max_answer_chars = -1;
```

### Return Schema

```ts
type FindSymbolOutput = FindSymbolMatch[] | string;

type FindSymbolMatch = SerenaSymbolReference & {
  children?: Record<string, string[] | SerenaChildSymbol[]>;
};
```

Example:

```json
[
  {
    "name_path": "SerenaBridgeClient",
    "kind": "Class",
    "relative_path": "src/bridge-client.ts",
    "body_location": {
      "start_line": 68,
      "end_line": 249
    }
  }
]
```

If `depth >= 1`, children may be included:

```json
[
  {
    "name_path": "SerenaBridgeClient",
    "kind": "Class",
    "relative_path": "src/bridge-client.ts",
    "body_location": {
      "start_line": 68,
      "end_line": 249
    },
    "children": {
      "Method": ["request", "shutdown"]
    }
  }
]
```

If `max_matches` is exceeded, Serena may return plain text with shortened candidates.

## get_symbol_from_snippet

Converts a concrete source occurrence into Serena-style symbol references.

Use this when the model wants to point at a usage site, such as `add` in `c.add(3)`.

### Input Schema

```ts
type GetSymbolFromSnippetInput = {
  relative_path: string;
  code_snippet: string;
  symbol_text: string;
  line?: number;
  column?: number;
  resolve?: "declaration" | "type_definition";
};
```

Default: `resolve = "declaration"`.

`line` and `column` are optional 0-based filters for ambiguous repeated snippets. `line` keeps only snippet occurrences spanning that line. `column` requires `line` and keeps only occurrences whose `symbol_text` covers that column.

### Return Schema

```ts
type GetSymbolFromSnippetOutput = {
  matches: SerenaSymbolReference[];
  locations?: LspLocation[];
  unresolved?: {
    reason: "no_lsp_target" | "external_or_unindexed_target";
    message: string;
  };
};
```

Example:

```json
{
  "matches": [
    {
      "name_path": "Calculator/add",
      "kind": "Method",
      "relative_path": "src/calculator.ts",
      "body_location": {
        "start_line": 2,
        "end_line": 4
      }
    }
  ]
}
```

If the snippet appears multiple times, all resolved symbols are returned. The model should inspect `body_location` with native read tools or retry with a more specific `code_snippet`.

If `matches` is empty, `unresolved` explains the targeted failure mode:

- `no_lsp_target`: the language server did not return a declaration/type-definition target.
- `external_or_unindexed_target`: the language server returned location(s), but the target could not be converted into a Serena project symbol. In this case `locations` contains the raw LSP locations.

Use `resolve: "type_definition"` when the model needs the concrete type/class/interface behind a source occurrence:

```json
{
  "relative_path": "src/main.ts",
  "code_snippet": "c.add(3)",
  "symbol_text": "c",
  "resolve": "type_definition"
}
```

If no match is found:

```json
{
  "matches": []
}
```

## find_referencing_symbols

Finds symbols that reference a Serena symbol.

### Input Schema

```ts
type FindReferencingSymbolsInput = {
  relative_path: string;
  name_path: string;
  kinds?: number[];
};
```

Hardcoded internally:

```ts
exclude_kinds = [];
max_answer_chars = -1;
```

### Return Schema

Serena-style grouped references.

```ts
type FindReferencingSymbolsOutput = Record<
  string,
  Record<string, ReferenceSymbol[]>
>;

type ReferenceSymbol = SerenaSymbolReference & {
  content_around_reference?: string;
};
```

Example:

```json
{
  "src/extension.ts": {
    "Class": [
      {
        "name_path": "default/execute",
        "kind": "Class",
        "relative_path": "src/extension.ts",
        "body_location": {
          "start_line": 40,
          "end_line": 90
        },
        "content_around_reference": "..."
      }
    ]
  }
}
```

Note: this keeps Serena's native reference output shape, including `content_around_reference`.

## find_declaration

Finds the declaration/definition for a Serena symbol.

### Input Schema

```ts
type FindDeclarationInput = {
  relative_path: string;
  name_path: string;
};
```

### Return Schema

Normalized row-oriented output:

```ts
type FindDeclarationOutput = {
  symbols: SerenaSymbolReference[];
  locations?: LspLocation[];
};
```

`symbols` contains converted Serena-style symbol references when possible. If the language server returns no declaration for a symbol that Serena already resolved, the wrapper returns the resolved Serena symbol itself as the declaration fallback. `locations` is only present when raw language-server locations are returned and cannot be converted to symbols.

No source body is returned.

## find_implementations

Finds implementations for a Serena symbol when the active language server supports `textDocument/implementation`.

### Input Schema

```ts
type FindImplementationsInput = {
  relative_path: string;
  name_path: string;
};
```

### Return Schema

Normalized row-oriented output:

```ts
type FindImplementationsOutput = {
  symbols: SerenaSymbolReference[];
  locations?: LspLocation[];
};
```

`symbols` contains converted Serena-style symbol references when possible. `locations` is only present when the language server returns raw locations that cannot be converted to symbols.

No source body is returned.

If the active language server does not support implementations, the tool returns a Serena-style plain text error message.

## rename_symbol

Renames a Serena symbol across the project using the active language server's rename support.

### Input Schema

```ts
type RenameSymbolInput = {
  relative_path: string;
  name_path: string;
  new_name: string;
};
```

### Return Schema

Serena plain status text.

```ts
type RenameSymbolOutput = string;
```

Example:

```text
Successfully renamed 'Calculator/add' to 'sum' (3 changes applied)
```

If `name_path` is ambiguous, the wrapper should raise a Serena-style `ValueError` with enriched candidates:

```text
Found multiple 2 symbols matching 'Model/getName'. They are:
[
  {
    "name_path": "Model/getName[0]",
    "kind": "Method",
    "relative_path": "src/Model.java",
    "body_location": {
      "start_line": 42,
      "end_line": 45
    }
  },
  {
    "name_path": "Model/getName[1]",
    "kind": "Method",
    "relative_path": "src/Model.java",
    "body_location": {
      "start_line": 48,
      "end_line": 51
    }
  }
]
```

No rename is applied when ambiguity remains.

## Usage Flow

If the model already has a Serena symbol:

```json
{
  "relative_path": "src/calculator.ts",
  "name_path": "Calculator/add"
}
```

it can call `find_referencing_symbols`, `find_declaration`, `find_implementations`, or `rename_symbol` directly.

If the model starts from a source usage:

```json
{
  "relative_path": "src/main.ts",
  "code_snippet": "c.add(3)",
  "symbol_text": "add"
}
```

it first calls `get_symbol_from_snippet`, then uses one returned `{ relative_path, name_path }` in follow-up tools.

For type-definition lookup, it calls `get_symbol_from_snippet` with `resolve: "type_definition"` and uses the returned symbol reference directly.

## Error Convention

Keep Serena's convention for execution failures:

```ts
type JsonlErrorResponse = {
  id: string;
  error: string;
};
```

The `error` field contains plain text, often a Python exception summary. Avoid structured custom error objects unless the entire bridge moves to structured errors later.
