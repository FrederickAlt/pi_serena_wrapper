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

  // -- lifecycle ----------------------------------------------------------

  pi.on("session_shutdown", async (_event, _ctx) => {
    if (client) {
      await client.shutdown();
      client = undefined;
    }
  });
}
