/**
 * ============================================================================
 * SYNC CONTRACT: tool-contracts.json (src/) is the single source of
 * truth for all parameter types, required fields, and descriptions across the
 * TypeScript ↔ Python seam.
 *
 * - The TypeBox schemas below MUST stay in sync with tool-contracts.json.
 *   When changing a parameter, update BOTH files.
 * - toolDescriptions is derived from tool-contracts.json at runtime to avoid
 *   duplicating description strings.
 * ============================================================================
 */

import { Type } from "@sinclair/typebox";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const contractPath = join(__dirname, "tool-contracts.json");

const require = createRequire(import.meta.url);
interface ContractTool {
  description: string;
  params: {
    type: "object";
    properties: Record<string, { type: string; description?: string; enum?: string[]; items?: { type: string } }>;
    required?: string[];
  };
}
interface ToolContracts {
  tools: Record<string, ContractTool>;
}
const contract: ToolContracts = require(contractPath);

// ---------------------------------------------------------------------------
// Shared reusable TypeBox fragments (mirrors the contract's common types)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Tool schemas — kept in TypeScript because TypeBox features (Type.Union,
// Type.Literal, Type.Optional) do not translate 1:1 to JSON Schema.
// ---------------------------------------------------------------------------

export const toolSchemas = {
  get_type: Type.Object({
    name_path: NamePath,
    relative_path: Type.Optional(RelativePath),
  }),

  get_document_symbols: Type.Object({
    relative_path: RelativePath,
    depth: Type.Optional(Type.Number({ description: "Descendant depth to include. Default 0." })),
  }),

  find_symbol: Type.Object({
    name_path: Type.String({ description: "Serena symbol name path pattern. Matched component-by-component, right-to-left, each component exact. Use leading / for absolute (exact full) match." }),
    relative_path: Type.Optional(RelativePath),
    code_snippet: Type.Optional(Type.String({
      description: "Exact source code snippet to scope the search via rg. Only symbols whose location falls within a snippet occurrence are returned.",
    })),
    kinds: KindList,
    max_matches: Type.Optional(Type.Number({ description: "Maximum number of symbol matches to return. Default 10. -1 means unlimited." })),
  }),

  get_references: Type.Object({
    name_path: NamePath,
    relative_path: Type.Optional(RelativePath),
  }),

  get_implementations: Type.Object({
    name_path: NamePath,
    relative_path: Type.Optional(RelativePath),
  }),

  rename_symbol: Type.Object({
    ...NamePathLookup,
    new_name: Type.String({ description: "New symbol name. The language server may reject rename if the workspace has errors." }),
  }),

  get_docstring: Type.Object({
    name_path: NamePath,
    relative_path: Type.Optional(RelativePath),
  }),
} as const;

// ---------------------------------------------------------------------------
// Tool descriptions — derived from tool-contracts.json at runtime.
// Throws at startup if the contract is missing an entry.
// ---------------------------------------------------------------------------

function buildToolDescriptions(): Record<keyof typeof toolSchemas, string> {
  const descriptions: Record<string, string> = {};
  for (const name of Object.keys(toolSchemas) as Array<keyof typeof toolSchemas>) {
    const entry = contract.tools[name];
    if (!entry) {
      throw new Error(
        `tool-contracts.json is missing entry for "${name}". ` +
        "Add the tool definition to the contract file.",
      );
    }
    descriptions[name] = entry.description;
  }
  return descriptions as Record<keyof typeof toolSchemas, string>;
}

export const toolDescriptions = buildToolDescriptions();

export type SerenaToolName = keyof typeof toolSchemas;

export const serenaToolNames = Object.keys(toolSchemas) as SerenaToolName[];
