import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { SerenaBridgeClient } from "./bridge-client.js";
import { toolSchemas, toolDescriptions, type SerenaToolName } from "./schemas.js";

export default function (pi: ExtensionAPI) {
  let client: SerenaBridgeClient | undefined;

  function clientFor(): SerenaBridgeClient {
    if (!client) {
      client = new SerenaBridgeClient();
    }
    return client;
  }

  // -----------------------------------------------------------------------
  // Tool: get_implementations
  // -----------------------------------------------------------------------

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
      // Ensure the bridge is initialized for the current working directory.
      // The cwd is made available via pi context but we pass "" to let the
      // bridge detect it from the environment or prior init.
      // For now we rely on the bridge having been initialized.
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

  // -----------------------------------------------------------------------

  pi.on("session_shutdown", async (_event, _ctx) => {
    if (client) {
      await client.shutdown();
      client = undefined;
    }
  });
}
