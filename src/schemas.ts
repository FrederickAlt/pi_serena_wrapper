import { Type } from "@sinclair/typebox";

const RelativePath = Type.String({
  description: "Path to a source file or directory, relative to the current project root.",
});

const NamePath = Type.String({
  description: "Serena symbol name path for a named code entity in the symbol tree, for example MyClass/my_method or /MyClass/my_method.",
});

const KindList = Type.Optional(Type.Array(Type.Number(), {
  description: "LSP SymbolKind integer values.",
}));

const NamePathLookup = {
  relative_path: RelativePath,
  name_path: NamePath,
} as const;

export const toolSchemas = {
  get_symbols_overview: Type.Object({
    relative_path: RelativePath,
    depth: Type.Optional(Type.Number({ description: "Descendant depth to include. Default 0." })),
  }),

  find_symbol: Type.Object({
    name_path_pattern: Type.String({ description: "Name path pattern to search for." }),
    depth: Type.Optional(Type.Number({ description: "Descendant depth to include. Default 0." })),
    relative_path: Type.Optional(RelativePath),
    kinds: KindList,
    max_matches: Type.Optional(Type.Number({ description: "Maximum matches before Serena returns a shortened result." })),
  }),

  get_symbol_from_snippet: Type.Object({
    relative_path: RelativePath,
    code_snippet: Type.String({
      description: "Exact source code snippet containing the symbol occurrence to resolve. Prefer enough surrounding code to make it unique.",
    }),
    symbol_text: Type.String({
      description: "Exact symbol text inside code_snippet where the LSP cursor should be placed.",
    }),
    resolve: Type.Optional(Type.Union([
      Type.Literal("declaration"),
      Type.Literal("type_definition"),
    ], { description: "Resolution mode. Default declaration." })),
  }),

  find_referencing_symbols: Type.Object({
    ...NamePathLookup,
    kinds: KindList,
  }),

  find_declaration: Type.Object({
    ...NamePathLookup,
  }),

  find_implementations: Type.Object({
    ...NamePathLookup,
  }),

  rename_symbol: Type.Object({
    ...NamePathLookup,
    new_name: Type.String({ description: "New symbol name. The language server may reject rename if the workspace has errors." }),
  }),
} as const;

export const toolDescriptions: Record<keyof typeof toolSchemas, string> = {
  get_symbols_overview: "Get a Serena top-level symbol overview for a source file.",
  find_symbol: "Search Serena's LSP symbol index by name path pattern.",
  get_symbol_from_snippet: "Resolve a concrete source occurrence to Serena-style symbol references.",
  find_referencing_symbols: "Find symbols that reference a given Serena symbol.",
  find_declaration: "Resolve the declaration/definition for a Serena symbol using Serena's LSP backend.",
  find_implementations: "Find implementations for a symbol using Serena's LSP backend when the active language server supports it.",
  rename_symbol: "Rename a symbol throughout the project using Serena's LSP refactoring.",
};

export type SerenaToolName = keyof typeof toolSchemas;

export const serenaToolNames = Object.keys(toolSchemas) as SerenaToolName[];
