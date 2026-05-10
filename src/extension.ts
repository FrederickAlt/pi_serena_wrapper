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

  // -- find_symbol --------------------------------------------------------

  pi.registerTool({
    name: "find_symbol" satisfies SerenaToolName,
    label: "Find Symbol",
    description: toolDescriptions.find_symbol,
    parameters: toolSchemas.find_symbol,
    async execute(_toolCallId, params, signal) {
      const result = await clientFor().callTool("find_symbol", params as Record<string, unknown>, signal);
      const text = JSON.stringify(result, null, 2);
      return {
        content: [{ type: "text" as const, text }],
        details: result,
      };
    },
  });

  // -- get_document_symbols -----------------------------------------------

  pi.registerTool({
    name: "get_document_symbols",
    label: "Get Document Symbols",
    description: toolDescriptions.get_document_symbols,
    parameters: toolSchemas.get_document_symbols,
    promptGuidelines: [
      "Prefer get_document_symbols over read/grep for understanding the structure of a source file.",
      "Use depth=1 to see top-level symbols and their immediate children (e.g. class members).",
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
      const c = clientFor();
      try {
        const result = await c.callTool("get_type", params as Record<string, unknown>, signal);
        return {
          content: [{ type: "text", text: JSON.stringify(result) }],
          details: result,
        } satisfies AgentToolResult<unknown>;
      } catch (err) {
        if (err instanceof SerenaError && err.errorKind === "ambiguity") {
          const errorResult = {
            error: err.message,
            candidates: err.errorData.candidates,
          };
          return {
            content: [{ type: "text", text: JSON.stringify(errorResult) }],
            details: errorResult,
          } satisfies AgentToolResult<unknown>;
        }
        throw err;
      }
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
    async execute(_toolCallId, params, signal) {
      const bridge = clientFor();
      const result = await bridge.callTool("get_references", params as Record<string, unknown>, signal);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
        details: result,
      };
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
      const c = clientFor();
      const result = await c.callTool("get_implementations", params as Record<string, unknown>, signal);
      if (result && typeof result === "object" && "error" in result) {
        return {
          content: [{ type: "text" as const, text: `Error: ${(result as Record<string, unknown>).error}` }],
          details: {},
        };
      }
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
        details: {},
      };
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
    async execute(_toolCallId, params, signal) {
      const bridge = clientFor();
      const text = await bridge.callTool("get_docstring", params as Record<string, unknown>, signal) as string;
      return {
        content: [{ type: "text" as const, text }],
        details: {},
      };
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
    async execute(_toolCallId, params, signal) {
      const bridge = clientFor();
      const text = await bridge.callTool("rename_symbol", params as Record<string, unknown>, signal) as string;
      return {
        content: [{ type: "text" as const, text }],
        details: {},
      };
    },
  });

  pi.on("session_shutdown", async (_event, _ctx) => {
    if (client) {
      await client.shutdown();
      client = undefined;
    }
  });
}
