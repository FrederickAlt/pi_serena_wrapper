import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { run, pi } from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

const reportFile = "pi-test-report.md";

const result = await run({
  agent: pi("gpt-oss-20b-mxfp4"),
  sandbox: docker({
    network: "host",
    mounts: [
      {
        hostPath: "~/.pi/agent",
        sandboxPath: "/home/agent/.pi/agent",
        readonly: true,
      },
    ],
  }),
  branchStrategy: { type: "branch", branch: `pi/test-disposable-${Date.now()}` },
  promptFile: "./.sandcastle/prompt.md",
});

if (result.preservedWorktreePath) {
  const reportPath = join(result.preservedWorktreePath, reportFile);
  const report = await readFile(reportPath, "utf8");
  console.log("\n===== PI TEST REPORT =====\n");
  console.log(report);
}
