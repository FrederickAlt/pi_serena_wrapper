import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { SerenaBridgeClient } from "./bridge-client.js";
import { toolSchemas, toolDescriptions } from "./schemas.js";

export default function (pi: ExtensionAPI) {
  let client: SerenaBridgeClient | undefined;

  function clientFor(): SerenaBridgeClient {
    if (!client) {
      client = new SerenaBridgeClient();
    }
    return client;
  }

  // ---- rename_symbol ---------------------------------------------------

  pi.registerTool({
    name: "rename_symbol",
    label: "Rename Symbol",
    description: toolDescriptions.rename_symbol,
    parameters: toolSchemas.rename_symbol,
    promptGuidelines: [
      "Prefer rename_symbol for refactoring symbol names across the project. Always verify the name_path via find_symbol first when the match is ambiguous.",
    ],
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const bridge = clientFor();
      await bridge.init(ctx.cwd, signal);
      const result = await bridge.callTool("rename_symbol", params as Record<string, unknown>, signal);
      const text = typeof result === "string" ? result : JSON.stringify(result, null, 2);
      return {
        content: [
          {
            type: "text" as const,
            text,
          },
        ],
        details: { result: text },
      };
    },
  });

  // ---- lifecycle -------------------------------------------------------

  pi.on("session_shutdown", async (_event, _ctx) => {
    if (client) {
      await client.shutdown();
      client = undefined;
    }
  });
}
