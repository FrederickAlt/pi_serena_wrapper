import { Type } from "@sinclair/typebox";

const MaxAnswerChars = Type.Optional(Type.Number({
  description: "Maximum number of characters in the Serena response. -1 uses Serena's default.",
}));

const RelativePath = Type.String({
  description: "Path to a source file or directory, relative to the current project root.",
});

const NamePath = Type.String({
  description: "Serena symbol name path, for example MyClass/my_method or /MyClass/my_method.",
});

const KindList = Type.Optional(Type.Array(Type.Number(), {
  description: "LSP SymbolKind integer values.",
}));

const SourceOccurrenceLookup = {
  relative_path: RelativePath,
  regex: Type.Optional(Type.String({
    description: "Regex with one capture group identifying the symbol occurrence to resolve.",
  })),
  code_snippet: Type.Optional(Type.String({
    description: "Exact source code snippet containing the symbol occurrence to resolve. Prefer enough surrounding code to make it unique in the file.",
  })),
  symbol_text: Type.Optional(Type.String({
    description: "Exact symbol text inside code_snippet where the LSP cursor should be placed, for example ReadDefinition.",
  })),
  occurrence_index: Type.Optional(Type.Number({
    description: "0-based occurrence to use when regex or code_snippet matches multiple locations. Prefer making code_snippet unique first.",
  })),
  line: Type.Optional(Type.Number({ description: "0-based line for direct LSP lookup." })),
  column: Type.Optional(Type.Number({ description: "0-based column for direct LSP lookup." })),
  include_body: Type.Optional(Type.Boolean({ description: "Include the resolved symbol body when available." })),
} as const;

export const toolSchemas = {
  get_symbols_overview: Type.Object({
    relative_path: RelativePath,
    depth: Type.Optional(Type.Number({ description: "Descendant depth to include. Default 0." })),
    max_answer_chars: MaxAnswerChars,
  }),

  find_symbol: Type.Object({
    name_path_pattern: Type.String({ description: "Name path pattern to search for." }),
    depth: Type.Optional(Type.Number({ description: "Descendant depth to include. Default 0." })),
    relative_path: Type.Optional(RelativePath),
    include_body: Type.Optional(Type.Boolean({ description: "Include symbol source body." })),
    include_info: Type.Optional(Type.Boolean({ description: "Include hover-like symbol info when available." })),
    include_kinds: KindList,
    exclude_kinds: KindList,
    substring_matching: Type.Optional(Type.Boolean({ description: "Use substring matching for the final path component." })),
    max_matches: Type.Optional(Type.Number({ description: "Maximum matches before Serena returns a shortened result." })),
    max_answer_chars: MaxAnswerChars,
  }),

  find_referencing_symbols: Type.Object({
    name_path: NamePath,
    relative_path: RelativePath,
    include_kinds: KindList,
    exclude_kinds: KindList,
    max_answer_chars: MaxAnswerChars,
  }),

  find_declaration: Type.Object({
    ...SourceOccurrenceLookup,
    name_path: Type.Optional(NamePath),
  }),

  find_type_definition: Type.Object({
    ...SourceOccurrenceLookup,
  }),

  find_implementations: Type.Object({
    relative_path: RelativePath,
    name_path: Type.Optional(NamePath),
    line: Type.Optional(Type.Number({ description: "0-based line for direct LSP lookup." })),
    column: Type.Optional(Type.Number({ description: "0-based column for direct LSP lookup." })),
    include_body: Type.Optional(Type.Boolean({ description: "Include implementation bodies when available." })),
  }),

  rename_symbol: Type.Object({
    name_path: NamePath,
    relative_path: RelativePath,
    new_name: Type.String({ description: "New symbol name. The language server may reject rename if the workspace has errors." }),
  }),
} as const;

export const toolDescriptions: Record<keyof typeof toolSchemas, string> = {
  get_symbols_overview: "Get a Serena top-level symbol overview for a source file.",
  find_symbol: "Search Serena's LSP symbol index by name path pattern.",
  find_referencing_symbols: "Find symbols that reference a given Serena symbol.",
  find_declaration: "Resolve the declaration/definition for a symbol occurrence using Serena's LSP backend.",
  find_type_definition: "Resolve the type/class/interface behind a source occurrence using Serena's LSP backend.",
  find_implementations: "Find implementations for a symbol using Serena's LSP backend when the active language server supports it.",
  rename_symbol: "Rename a symbol throughout the project using Serena's LSP refactoring.",
};

export type SerenaToolName = keyof typeof toolSchemas;

export const serenaToolNames = Object.keys(toolSchemas) as SerenaToolName[];
