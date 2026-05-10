import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { SerenaBridgeClient } from "./bridge-client.js";

export default function (pi: ExtensionAPI) {
  let client: SerenaBridgeClient | undefined;

  function clientFor(): SerenaBridgeClient {
    if (!client) {
      client = new SerenaBridgeClient();
    }
    return client;
  }

  // No tools registered yet — only init/shutdown lifecycle.
  // Tools will be added in follow-up issues (see GitHub issues #2–#10).

  pi.on("session_shutdown", async (_event, _ctx) => {
    if (client) {
      await client.shutdown();
      client = undefined;
    }
  });
}
