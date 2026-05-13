import type { ExtensionAPI, AgentToolResult, ToolRenderContext } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";
import { SerenaBridgeClient, SerenaError } from "./bridge-client.js";
import { toolSchemas, toolDescriptions, type SerenaToolName } from "./schemas.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function str(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "???";
  return String(value);
}

// ---------------------------------------------------------------------------
// Tool registry — single source of truth for registration
// ---------------------------------------------------------------------------

interface ToolEntry {
  name: SerenaToolName;
  label: string;
  guidelines?: string[];
  renderCall?: (args: Record<string, unknown>, theme: any, context: ToolRenderContext<any, any>) => any;
}

type ExecuteFn = (
  params: Record<string, unknown>,
  signal: AbortSignal | undefined,
  client: SerenaBridgeClient,
) => Promise<AgentToolResult<unknown>>;

const TOOLS: (ToolEntry & { execute: ExecuteFn })[] = [
  {
    name: "find_symbol",
    label: "Find Symbol",
    guidelines: [
      "Returns a flat array of symbol entries: {name_path, kind, location}.",
      "When results are truncated beyond max_matches, a sentinel entry {name_path: '--truncated--', kind: 'None', location: 'None'} is appended.",
      "Strip or skip this sentinel when processing results. Its presence means more symbols exist than were returned.",
    ],
    execute: stdCallTool("find_symbol"),
    renderCall(args, theme, context) {
      const text = context.lastComponent ?? new Text("", 0, 0);
      let line = theme.fg("toolTitle", theme.bold("find_symbol")) + " " + theme.fg("accent", str(args.name_path));
      if (args.relative_path) line += theme.fg("toolOutput", " in ") + theme.fg("accent", str(args.relative_path));
      if (args.kinds) line += theme.fg("toolOutput", " kinds:") + theme.fg("accent", JSON.stringify(args.kinds));
      if (args.code_snippet) line += theme.fg("toolOutput", " snippet:") + theme.fg("accent", JSON.stringify(args.code_snippet));
      if (args.max_matches !== undefined) line += theme.fg("toolOutput", ` max:${args.max_matches}`);
      text.setText(line);
      return text;
    },
  },
  {
    name: "get_document_overview",
    label: "Get Document Overview",
    guidelines: [
      "Use get_document_overview to get a two-section plain-text overview of a source file: Imports and Symbols.",
      "The Imports section shows each source module with its imported names, classified as [internal] or [external].",
      "Internal imports are resolved to their definition file and line range (e.g. [internal → src/utils.ts:1-3]).",
      "The Symbols section shows each locally-defined symbol with Kind Name:startLine-endLine, 2-space indented by nesting.",
      "Imported bindings are excluded from the Symbols section.",
      "Use depth to control nesting (0 = top-level only, 1 = one level of children, etc.). Default 0.",
      "The default kinds filter excludes noisy leaf kinds (Property, Field, Variable, File, Package, String, Number, Boolean, Array, Object, Key, Null, Operator, Unknown). Override with kinds to include them or narrow further.",
      "For languages without import parser support (non-TS/Python), the Imports section is omitted but Symbols still work.",
    ],
    execute: stdTextCallTool("get_document_overview"),
    renderCall(args, theme, context) {
      const text = context.lastComponent ?? new Text("", 0, 0);
      let line = theme.fg("toolTitle", theme.bold("get_document_overview")) + " " + theme.fg("accent", str(args.relative_path));
      if (args.depth !== undefined && args.depth !== 0) line += theme.fg("toolOutput", ` depth:${args.depth}`);
      if (args.kinds) line += theme.fg("toolOutput", " kinds:") + theme.fg("accent", JSON.stringify(args.kinds));
      text.setText(line);
      return text;
    },
  },
  {
    name: "get_type",
    label: "Get Type",
    guidelines: [
      "Use this tool when you need to identify the type of a symbol (interface, class, type alias, enum, etc.).",
      "Provide an exact name_path (e.g. \"MyInterface\" or \"MyClass/myMethod\"). See the name_path documentation for details on pattern matching.",
      "If the result is ambiguous, you'll receive a list of candidates. Use find_symbol first to narrow down the possibilities.",
      "relative_path is optional — provide it to narrow which file/directory to search for the symbol definition. The resolved type info is always project-wide.",
      "The result is a compact symbol dict with name_path, kind, and location.",
    ],
    execute: stdCallTool("get_type"),
    renderCall(args, theme, context) {
      const text = context.lastComponent ?? new Text("", 0, 0);
      let line = theme.fg("toolTitle", theme.bold("get_type")) + " " + theme.fg("accent", str(args.name_path));
      if (args.relative_path) line += theme.fg("toolOutput", " in ") + theme.fg("accent", str(args.relative_path));
      text.setText(line);
      return text;
    },
  },
  {
    name: "get_references",
    label: "Get References",
    guidelines: [
      "Use get_references to find all usages of a symbol across the codebase.",
      "Provide the full Serena name_path (e.g. MyClass/myMethod) to identify the symbol.",
      "Optionally scope the search with relative_path to narrow which file/directory to search for the symbol definition. Reference results are always project-wide.",
      "Each result includes referrer (enclosing scope), kind, and location (file:startLine-endLine).",
    ],
    execute: stdCallTool("get_references"),
    renderCall(args, theme, context) {
      const text = context.lastComponent ?? new Text("", 0, 0);
      let line = theme.fg("toolTitle", theme.bold("get_references")) + " " + theme.fg("accent", str(args.name_path));
      if (args.relative_path) line += theme.fg("toolOutput", " in ") + theme.fg("accent", str(args.relative_path));
      text.setText(line);
      return text;
    },
  },
  {
    name: "get_implementations",
    label: "Get Implementations",
    guidelines: [
      "Use `get_implementations` to find implementing symbols for a given interface/abstract method via Serena's LSP.",
      "Provide `name_path` (required) to identify the symbol. Optionally pass `relative_path` to narrow which file/directory to search for the symbol definition. Implementation results are always project-wide.",
    ],
    execute: stdCallTool("get_implementations"),
    renderCall(args, theme, context) {
      const text = context.lastComponent ?? new Text("", 0, 0);
      let line = theme.fg("toolTitle", theme.bold("get_implementations")) + " " + theme.fg("accent", str(args.name_path));
      if (args.relative_path) line += theme.fg("toolOutput", " in ") + theme.fg("accent", str(args.relative_path));
      text.setText(line);
      return text;
    },
  },
  {
    name: "get_docstring",
    label: "Get Docstring",
    guidelines: [
      "Use get_docstring to retrieve documentation/hover text for a symbol.",
      "Provide the name_path to identify the symbol. Optionally scope with relative_path to narrow where to search for the symbol definition.",
      "Returns a plain string with the hover content, or 'No docstring available.'.",
    ],
    execute: stdCallTool("get_docstring"),
    renderCall(args, theme, context) {
      const text = context.lastComponent ?? new Text("", 0, 0);
      let line = theme.fg("toolTitle", theme.bold("get_docstring")) + " " + theme.fg("accent", str(args.name_path));
      if (args.relative_path) line += theme.fg("toolOutput", " in ") + theme.fg("accent", str(args.relative_path));
      text.setText(line);
      return text;
    },
  },
  {
    name: "rename_symbol",
    label: "Rename Symbol",
    guidelines: [
      "Use rename_symbol to rename a symbol across the entire project via LSP.",
      "Provide the name_path of the symbol to rename, the new_name, and optionally a relative_path to narrow which file/directory to search for the symbol definition.",
      "The rename applies only the edits returned by the language server; some servers may not propagate renames to import sites in other files.",
    ],
    execute: stdCallTool("rename_symbol"),
    renderCall(args, theme, context) {
      const text = context.lastComponent ?? new Text("", 0, 0);
      let line = theme.fg("toolTitle", theme.bold("rename_symbol")) + " " + theme.fg("accent", str(args.name_path));
      line += theme.fg("toolOutput", " → ") + theme.fg("accent", str(args.new_name));
      if (args.relative_path) line += theme.fg("toolOutput", " in ") + theme.fg("accent", str(args.relative_path));
      text.setText(line);
      return text;
    },
  },
  {
    name: "restart_lsp",
    label: "Restart LSP",
    execute: async (_params, _signal, client) => {
      const result = await client.restart((_params as Record<string, unknown>).cwd as string);
      return {
        content: [{ type: "text", text: JSON.stringify(result) }],
        details: result,
      };
    },
    renderCall(args, theme, context) {
      const text = context.lastComponent ?? new Text("", 0, 0);
      text.setText(theme.fg("toolTitle", theme.bold("restart_lsp")) + " " + theme.fg("accent", str(args.cwd)));
      return text;
    },
  },
];

// ---------------------------------------------------------------------------
// Execute factories
// ---------------------------------------------------------------------------

/** Standard JSON tool call with ambiguity wrapping. */
function stdCallTool(toolName: string): ExecuteFn {
  return async (params, signal, client) =>
    wrapAmbiguity(() => client.callTool(toolName, params, signal));
}

/** Tool call that returns a plain text string (no JSON wrapping). */
function stdTextCallTool(toolName: string): ExecuteFn {
  return async (params, signal, client) => {
    const text = await client.callTool(toolName, params, signal) as string;
    return {
      content: [{ type: "text" as const, text }],
      details: {},
    };
  };
}

// ---------------------------------------------------------------------------
// Ambiguity wrapper
// ---------------------------------------------------------------------------

async function wrapAmbiguity(call: () => Promise<unknown>): Promise<AgentToolResult<unknown>> {
  try {
    const result = await call();
    return {
      content: [{ type: "text", text: JSON.stringify(result) }],
      details: result,
    };
  } catch (err) {
    if (err instanceof SerenaError && err.errorKind === "ambiguity") {
      const errorResult = {
        error: err.message,
        candidates: err.errorData.candidates,
      };
      return {
        content: [{ type: "text", text: JSON.stringify(errorResult) }],
        details: errorResult,
      };
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Extension entry point
// ---------------------------------------------------------------------------

export default function (pi: ExtensionAPI) {
  let client: SerenaBridgeClient | undefined;

  function clientFor(): SerenaBridgeClient {
    if (!client) {
      client = new SerenaBridgeClient();
    }
    return client;
  }

  for (const tool of TOOLS) {
    pi.registerTool({
      name: tool.name satisfies SerenaToolName,
      label: tool.label,
      description: toolDescriptions[tool.name],
      parameters: toolSchemas[tool.name],
      promptGuidelines: tool.guidelines,
      renderCall: tool.renderCall,
      execute: async (_toolCallId, params, signal) => {
        return tool.execute(params as Record<string, unknown>, signal, clientFor());
      },
    });
  }

  pi.on("session_start", async (_event, ctx) => {
    await clientFor().init(ctx.cwd);
  });

  pi.on("session_shutdown", async (_event, _ctx) => {
    if (client) {
      await client.shutdown();
      client = undefined;
    }
  });
}
