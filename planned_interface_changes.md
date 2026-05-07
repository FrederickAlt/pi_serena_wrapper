# Planned Interface Changes

## find_symbol New Interface Draft

## Input Schema

```ts
type FindSymbolInput = {
  name_path_pattern: string;
  relative_path?: string;
  depth?: number;
  kinds?: number[];
  max_matches?: number;
};
```

Implementation note:

- `include_body` is removed from the public interface and hardcoded to `false`.
- `include_info` is removed from the public interface and hardcoded to `false`.
- `max_answer_chars` is removed from the public interface.
- `substring_matching` is removed from the public interface and hardcoded to `false`.
- `exclude_kinds` is removed from the public interface.
- `kinds` uses standard LSP `SymbolKind` integer values. The model should be told this, but the mapping does not need to be included in the schema.

## Output Schema

```ts
type FindSymbolOutput = FindSymbolMatch[] | string;

type FindSymbolMatch = {
  name_path: string;
  kind: string;
  relative_path: string | null;
  body_location?: {
    start_line: number | null;
    end_line: number | null;
  };
  children?: Record<string, string[] | FindSymbolChild[]>;
};

type FindSymbolChild = {
  name?: string;
  kind?: string;
  body_location?: {
    start_line: number | null;
    end_line: number | null;
  };
  children?: Record<string, string[] | FindSymbolChild[]>;
};
```

`children` is only expected when `depth >= 1` and the language server reports child symbols. With `depth` omitted or `depth: 0`, the result should contain only the matched top-level symbols.

`FindSymbolOutput` can be `string` when Serena returns a shortened result, for example when `max_matches` cuts the response down.

## Related Planned Change: rename_symbol Ambiguity

Before handing off to Serena's `rename_symbol`, the wrapper should pre-resolve the requested `name_path`:

1. Call Serena's symbol retriever with `name_path` and `relative_path`.
2. If exactly one symbol matches, call Serena's normal `rename_symbol`.
3. If multiple symbols match but Serena's exact-match rule selects exactly one, call Serena's normal `rename_symbol`.
4. Otherwise raise a Serena-style `ValueError` with enriched candidates.

Error style:

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

This keeps Serena's plain-text `ValueError` convention while giving the model enough `body_location` information to inspect candidates with native read tools before retrying with the exact `name_path`.

The same enriched ambiguity handling should be used for every tool that resolves a unique `name_path` before calling Serena/LSP internals:

- `find_referencing_symbols`
- `find_declaration`
- `find_implementations`
- `rename_symbol`

All of them should raise Serena-style plain `ValueError` text with candidates containing:

```ts
type AmbiguousSymbolCandidate = {
  name_path: string;
  kind: string;
  relative_path: string | null;
  body_location?: {
    start_line: number | null;
    end_line: number | null;
  };
};
```

No source body should be included in ambiguity errors.

## New Tool: get_symbol_from_snippet

Purpose: convert a concrete source occurrence into a Serena-style symbol reference.

This lets us remove `code_snippet`, `symbol_text`, and `occurrence_index` from Serena-native/follow-up tools such as `find_referencing_symbols`, `find_implementations`, and `rename_symbol`. Those tools can stay in the Serena universe: `relative_path + name_path`.

This also replaces public `find_type_definition`. Type definition is naturally source-occurrence based, so it belongs here as a resolution mode instead of as a separate `name_path` follow-up tool.

### Input Schema

```ts
type GetSymbolFromSnippetInput = {
  relative_path: string;
  code_snippet: string;
  symbol_text: string;
  resolve?: "declaration" | "type_definition";
};
```

Default: `resolve = "declaration"`.

### Output Schema

```ts
type GetSymbolFromSnippetOutput = {
  matches: Array<{
    name_path: string;
    kind: string;
    relative_path: string | null;
    body_location?: {
      start_line: number | null;
      end_line: number | null;
    };
  }>;
};
```

Behavior:

1. Read `relative_path`.
2. Find every exact occurrence of `code_snippet`.
3. For each occurrence, find `symbol_text` inside that snippet. `symbol_text` must occur exactly once inside the snippet.
4. Convert that source position to internal LSP line/column.
5. If `resolve` is `"declaration"`, ask the Serena-managed language server for the declared symbol at that location.
6. If `resolve` is `"type_definition"`, ask the Serena-managed language server for the type definition at that location.
7. Return all resolved matches as Serena-style symbol references.

If there are multiple matches, return all resolved symbols. Do not accept `occurrence_index`; the model should inspect the returned `body_location`s with native read tools or call declaration tools if needed, then retry with a more specific `code_snippet`.

If there are no matches, return:

```json
{
  "matches": []
}
```

Follow-up tools then use the returned symbol directly:

```json
{
  "relative_path": "src/calculator.ts",
  "name_path": "Calculator/add"
}
```

## Per-Tool Migration Plan

Goal: remove custom source-occurrence parameters from all Serena-native/follow-up tools. `get_symbol_from_snippet` becomes the only tool that accepts `code_snippet` and `symbol_text`.

All symbolic read tools should be row-oriented: return symbol references and `body_location`, but not source body text. The model should use native file-read tools when it needs the actual source content.

Custom public parameters to remove everywhere except `get_symbol_from_snippet`:

- `code_snippet`
- `symbol_text`
- `occurrence_index`
- `regex`
- `include_body`

### get_symbols_overview

Keep Serena-compatible.

```ts
type GetSymbolsOverviewInput = {
  relative_path: string;
  depth?: number;
};
```

Changes:

- Remove `max_answer_chars` from public schema.
- Continue passing through Serena's compact overview output.

### find_symbol

Use the `find_symbol` schema above.

Changes:

- Remove `include_body`, `include_info`, `exclude_kinds`, `substring_matching`, and `max_answer_chars`.
- Hardcode removed values:
  - `include_body = false`
  - `include_info = false`
  - `exclude_kinds = []`
  - `substring_matching = false`
  - `max_answer_chars = -1`
- Keep Serena output shape.

### get_symbol_from_snippet

Add as the only source-occurrence conversion tool.

Changes:

- New tool schema and bridge method.
- Internally resolve snippet/token to LSP line/column.
- Support `resolve = "declaration"` and `resolve = "type_definition"`.
- Return Serena-style symbol references only.
- Return all matches; do not use `occurrence_index`.

### find_referencing_symbols

Make it Serena-style only.

```ts
type FindReferencingSymbolsInput = {
  relative_path: string;
  name_path: string;
  kinds?: number[];
};
```

Changes:

- Remove `code_snippet`, `symbol_text`, `occurrence_index`, `exclude_kinds`, and `max_answer_chars`.
- Hardcode:
  - `exclude_kinds = []`
  - `max_answer_chars = -1`
- Prefer handing off to Serena's native `FindReferencingSymbolsTool` for output consistency.
- If we keep a wrapper pre-resolution step for better ambiguity errors, preserve Serena's output shape on success.

### find_declaration

Use Serena-style symbol input only.

```ts
type FindDeclarationInput = {
  relative_path: string;
  name_path: string;
};
```

Changes:

- Remove `code_snippet`, `symbol_text`, `occurrence_index`, `regex`, and `include_body`.
- Resolve `name_path` with Serena, then return declaration location data without body source.
- Output should be row-oriented and not include source body.

Open design point:

- This is not a native Serena LSP tool. Decide whether the return should be Serena-style symbol reference(s), raw LSP locations, or a normalized wrapper shape. Prefer normalized wrapper shape if we want stable row-only output.

### find_type_definition

Remove as a public tool.

Reason:

- Type definition is source-occurrence based. Calling it on an already-selected declaration symbol is often redundant or language-server-dependent.
- Use `get_symbol_from_snippet` with `resolve: "type_definition"` instead.

### find_implementations

Use Serena-style symbol input only.

```ts
type FindImplementationsInput = {
  relative_path: string;
  name_path: string;
};
```

Changes:

- Remove `code_snippet`, `symbol_text`, `occurrence_index`, and `include_body`.
- Resolve `name_path` with Serena to an internal line/column, then call implementation through the Serena-managed LSP.
- Output should be row-oriented and not include source body.

Open design point:

- This is not a native Serena LSP tool. Decide whether unsupported LSP support should remain a plain text message or become a normalized no-support result.

### rename_symbol

Make it Serena-style only.

```ts
type RenameSymbolInput = {
  relative_path: string;
  name_path: string;
  new_name: string;
};
```

Changes:

- Remove `code_snippet`, `symbol_text`, and `occurrence_index`.
- Add pre-resolution for enriched ambiguity errors as described above.
- On unique match, hand off to Serena's normal `rename_symbol`.
- Preserve Serena's plain status text on success.

### Prompt/Usage Flow

If the model points at source text:

1. Call `get_symbol_from_snippet`.
2. Pick one returned Serena-style symbol reference.
3. Call the normal follow-up tool with `relative_path + name_path`.

Example:

```json
{
  "relative_path": "src/main.ts",
  "code_snippet": "c.add(3)",
  "symbol_text": "add"
}
```

Then:

```json
{
  "relative_path": "src/calculator.ts",
  "name_path": "Calculator/add",
  "new_name": "sum"
}
```

## Questions Before Implementation

- For custom non-Serena tools (`find_declaration`, `find_implementations`), should their returns be normalized to `{ symbols: [...] }` / `{ locations: [...] }`, or should they stay close to current raw LSP/Serena responses while removing bodies?
- Should `find_declaration` remain at all once `get_symbol_from_snippet` exists, or should it only handle declarations for external/usage-derived symbols in a later pass?
