import { run, pi } from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

// Blank template: customize this to build your own orchestration.
// Run this with: npx tsx .sandcastle/main.mts
// Or add to package.json scripts: "sandcastle": "npx tsx .sandcastle/main.mts"

await run({


  agent: pi("gpt-oss-20b-mxfp4"),
  sandbox: docker({
    network: "host",
    mounts: [
      {
        hostPath: "~/.pi/agent",
        sandboxPath: "/home/agent/.pi/agent",
        readonly: true,
      },
    ]
  }),
  branchStrategy: { type: "branch", branch: `pi/test-disposable-${Date.now()}` },
  promptFile: "./.sandcastle/prompt.md",
});
