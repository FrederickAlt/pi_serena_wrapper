import type { ExtensionAPI, AgentToolResult } from "@mariozechner/pi-coding-agent";
import { SerenaBridgeClient, SerenaError } from "./bridge-client.js";
import { toolSchemas, toolDescriptions, type SerenaToolName } from "./schemas.js";

export default function (pi: ExtensionAPI) {
  let client: SerenaBridgeClient | undefined;

  function clientFor(): SerenaBridgeClient {
    if (!client) {
      client = new SerenaBridgeClient();
    }
    return client;
  }

  /** Return tool result, with structured error info on symbol ambiguity. */
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

  // -- find_symbol --------------------------------------------------------

  pi.registerTool({
    name: "find_symbol" satisfies SerenaToolName,
    label: "Find Symbol",
    description: toolDescriptions.find_symbol,
    parameters: toolSchemas.find_symbol,
    execute: async (_toolCallId, params, signal) => {
      return wrapAmbiguity(() =>
        clientFor().callTool("find_symbol", params as Record<string, unknown>, signal),
      );
    },
  });

  // -- get_document_symbols (deprecated) ----------------------------------

  pi.registerTool({
    name: "get_document_symbols",
    label: "Get Document Symbols",
    description: toolDescriptions.get_document_symbols,
    parameters: toolSchemas.get_document_symbols,
    promptGuidelines: [
      "DEPRECATED: Prefer get_document_overview instead, which includes symbol line ranges and file imports.",
      "This tool returns only a structural outline without line ranges; get_document_overview provides both symbol ranges and import information.",
    ],
    execute: async (toolCallId, params, signal) => {
      const bridge = clientFor();
      const text = await bridge.callTool("get_document_symbols", params as Record<string, unknown>, signal) as string;
      return {
        content: [
          { type: "text" as const, text },
        ],
        details: {},
      };
    },
  });

  // -- get_document_overview ----------------------------------------------

  pi.registerTool({
    name: "get_document_overview",
    label: "Get Document Overview",
    description: toolDescriptions.get_document_overview,
    parameters: toolSchemas.get_document_overview,
    promptGuidelines: [
      "Use get_document_overview to get a two-section plain-text overview of a source file: Imports and Symbols.",
      "The Imports section shows each source module with its imported names, classified as [internal] or [external].",
      "Internal imports are resolved to their definition file and line range (e.g. [internal → src/utils.ts:1-3]).",
      "The Symbols section shows each locally-defined symbol with Kind Name:startLine-endLine, 2-space indented by nesting.",
      "Imported bindings are excluded from the Symbols section.",
      "Use depth to control nesting (0 = top-level only, 1 = one level of children, etc.). Default 0.",
      "For languages without import parser support (non-TS/Python), the Imports section is omitted but Symbols still work.",
    ],
    execute: async (toolCallId, params, signal) => {
      const bridge = clientFor();
      const text = await bridge.callTool("get_document_overview", params as Record<string, unknown>, signal) as string;
      return {
        content: [
          { type: "text" as const, text },
        ],
        details: {},
      };
    },
  });

  // -- get_type ------------------------------------------------------------

  pi.registerTool({
    name: "get_type",
    label: "Get Type",
    description: toolDescriptions.get_type,
    parameters: toolSchemas.get_type,
    promptGuidelines: [
      "Use this tool when you need to identify the type of a symbol (interface, class, type alias, enum, etc.).",
      "Provide an exact name_path (e.g. \"MyInterface\" or \"MyClass/myMethod\"). See the name_path documentation for details on pattern matching.",
      "If the result is ambiguous, you'll receive a list of candidates. Use find_symbol first to narrow down the possibilities.",
      "relative_path is optional — provide it to scope the search to a specific file or directory.",
      "The result is a compact symbol dict with name_path, kind, and location.",
    ],
    execute: async (_toolCallId, params, signal) => {
      return wrapAmbiguity(() =>
        clientFor().callTool("get_type", params as Record<string, unknown>, signal),
      );
    },
  });

  // -- get_references ------------------------------------------------------

  pi.registerTool({
    name: "get_references" as SerenaToolName,
    label: "Get References",
    description: toolDescriptions.get_references,
    parameters: toolSchemas.get_references,
    promptGuidelines: [
      "Use get_references to find all usages of a symbol across the codebase.",
      "Provide the full Serena name_path (e.g. MyClass/myMethod) to identify the symbol.",
      "Optionally scope the search with relative_path to limit results to a file or directory.",
      "Each result includes name_path, kind, and location (file:startLine-endLine).",
    ],
    execute: async (_toolCallId, params, signal) => {
      return wrapAmbiguity(() =>
        clientFor().callTool("get_references", params as Record<string, unknown>, signal),
      );
    },
  });

  // -- get_implementations -------------------------------------------------

  pi.registerTool({
    name: "get_implementations" satisfies SerenaToolName,
    label: "Get Implementations",
    description: toolDescriptions.get_implementations,
    parameters: toolSchemas.get_implementations,
    promptGuidelines: [
      "Use `get_implementations` to find implementing symbols for a given interface/abstract method via Serena's LSP.",
      "Provide `name_path` (required) to identify the symbol. Optionally pass `relative_path` to scope the search.",
    ],
    execute: async (_toolCallId, params, signal) => {
      return wrapAmbiguity(() =>
        clientFor().callTool("get_implementations", params as Record<string, unknown>, signal),
      );
    },
  });

  // -- get_docstring -------------------------------------------------------

  pi.registerTool({
    name: "get_docstring" as SerenaToolName,
    label: "Get Docstring",
    description: toolDescriptions.get_docstring,
    parameters: toolSchemas.get_docstring,
    promptGuidelines: [
      "Use get_docstring to retrieve documentation/hover text for a symbol.",
      "Provide the name_path to identify the symbol. Optionally scope with relative_path.",
      "Returns a plain string with the hover content, or 'No docstring available.'.",
    ],
    execute: async (_toolCallId, params, signal) => {
      return wrapAmbiguity(() =>
        clientFor().callTool("get_docstring", params as Record<string, unknown>, signal),
      );
    },
  });

  // -- rename_symbol -------------------------------------------------------

  pi.registerTool({
    name: "rename_symbol" satisfies SerenaToolName,
    label: "Rename Symbol",
    description: toolDescriptions.rename_symbol,
    parameters: toolSchemas.rename_symbol,
    promptGuidelines: [
      "Use rename_symbol to rename a symbol across the entire project via LSP.",
      "Provide the name_path of the symbol to rename, the new_name, and optionally a relative_path to scope the search.",
      "The rename is applied immediately — all affected files are modified on disk.",
    ],
    execute: async (_toolCallId, params, signal) => {
      return wrapAmbiguity(() =>
        clientFor().callTool("rename_symbol", params as Record<string, unknown>, signal),
      );
    },
  });

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
