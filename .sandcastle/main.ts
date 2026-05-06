import { run, pi } from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

// Blank template: customize this to build your own orchestration.
// Run this with: npx tsx .sandcastle/main.ts
// Or add to package.json scripts: "sandcastle": "npx tsx .sandcastle/main.ts"

await run({
  agent: pi("gpt-oss-20b-mxfp4"),
  sandbox: docker(),
  promptFile: "./.sandcastle/prompt.md",
});
