import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { SerenaBridgeClient } from "./bridge-client.js";
import {
  toolSchemas,
  toolDescriptions,
  type SerenaToolName,
} from "./schemas.js";

export default function (pi: ExtensionAPI) {
  let client: SerenaBridgeClient | undefined;

  function clientFor(): SerenaBridgeClient {
    if (!client) {
      client = new SerenaBridgeClient();
    }
    return client;
  }

  // -- tool: get_docstring --------------------------------------------------

  pi.registerTool({
    name: "get_docstring" satisfies SerenaToolName,
    label: "Get Docstring",
    description: toolDescriptions.get_docstring,
    promptSnippet: "get_docstring(\"MyClass/my_method\")",
    promptGuidelines: [
      "Use `get_docstring` to read hover documentation for a symbol identified by its Serena name path (e.g. `MyClass/my_method` or `/MyClass/my_method`).",
      "The `relative_path` parameter is optional and scopes the search to a file or directory.",
      "If the name path is ambiguous, the tool returns a candidate list — use a more qualified name path.",
    ],
    parameters: toolSchemas.get_docstring,
    async execute(_toolCallId, params, signal) {
      const bridge = clientFor();
      const cwd = process.env.SERENA_CWD ?? process.cwd();
      await bridge.init(cwd, signal);
      const response = (await bridge.callTool(
        "get_docstring",
        params as Record<string, unknown>,
        signal,
      )) as { result?: unknown };
      const text = String(response.result ?? "");
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
