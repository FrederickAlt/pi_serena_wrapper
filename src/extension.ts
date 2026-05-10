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
    execute: async (_toolCallId, params, signal, _onUpdate, _ctx) => {
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

  pi.on("session_shutdown", async (_event, _ctx) => {
    if (client) {
      await client.shutdown();
      client = undefined;
    }
  });
}
