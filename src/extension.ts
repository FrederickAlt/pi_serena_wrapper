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

  // -------------------------------------------------------------------------
  // get_references
  // -------------------------------------------------------------------------

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
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const bridge = clientFor();
      await bridge.init(ctx.cwd, signal);
      const result = await bridge.callTool("get_references", params as Record<string, unknown>, signal);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
        details: result,
      };
    },
  });

  // -------------------------------------------------------------------------
  // Lifecycle
  // -------------------------------------------------------------------------

  pi.on("session_shutdown", async (_event, _ctx) => {
    if (client) {
      await client.shutdown();
      client = undefined;
    }
  });
}
