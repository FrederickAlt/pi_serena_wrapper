import type { ExtensionAPI, ToolDefinition } from "@mariozechner/pi-coding-agent";
import { SerenaBridgeClient } from "./bridge-client.js";
import { toolSchemas, toolDescriptions } from "./schemas.js";
import type { SerenaToolName } from "./schemas.js";

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
      };
    },
  });

  // -- lifecycle ----------------------------------------------------------

  pi.on("session_shutdown", async (_event, _ctx) => {
    if (client) {
      await client.shutdown();
      client = undefined;
    }
  });
}
