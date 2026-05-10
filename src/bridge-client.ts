import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import * as path from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

import { SubprocessTransport, type JsonRpcTransport, DEFAULT_TIMEOUT_MS } from "./transport.js";

export { JsonValue } from "./transport.js";

// ---------------------------------------------------------------------------
// Helpers (Python environment management)
// ---------------------------------------------------------------------------

const execFileAsync = promisify(execFile);

function packageRoot(): string {
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
}

function setupCommand(root: string): string {
  return `cd ${root} && python3 -m venv .venv && .venv/bin/pip install --upgrade -r requirements.txt`;
}

function localPython(root: string): string {
  return path.join(root, ".venv", "bin", "python");
}

function localPip(root: string): string {
  return path.join(root, ".venv", "bin", "pip");
}

function requirementsPath(root: string): string {
  return path.join(root, "requirements.txt");
}

function commandText(command: string, args: string[]): string {
  return [command, ...args].join(" ");
}

function errorOutput(error: unknown): string {
  if (error && typeof error === "object") {
    const maybe = error as { stderr?: unknown; stdout?: unknown; message?: unknown };
    const stderr = typeof maybe.stderr === "string" ? maybe.stderr.trim() : "";
    const stdout = typeof maybe.stdout === "string" ? maybe.stdout.trim() : "";
    const message = typeof maybe.message === "string" ? maybe.message : "";
    return [stderr, stdout, message].filter(Boolean).join("\n");
  }
  return String(error);
}

async function runSetupCommand(command: string, args: string[], cwd: string): Promise<void> {
  try {
    await execFileAsync(command, args, { cwd, maxBuffer: 10 * 1024 * 1024 });
  } catch (error) {
    throw new Error(`Failed to run ${commandText(command, args)} in ${cwd}:\n${errorOutput(error)}`);
  }
}

// ---------------------------------------------------------------------------
// SerenaBridgeClient — protocol layer only (init + shutdown for now)
// ---------------------------------------------------------------------------

export class SerenaBridgeClient {
  private readonly transport: JsonRpcTransport;
  private initializedFor: string | undefined;

  constructor(private readonly root = packageRoot()) {
    const python = localPython(this.root);
    const script = path.join(this.root, "bridge", "serena_pi_bridge.py");
    this.transport = new SubprocessTransport(python, script, {
      cwd: this.root,
      env: {
        ...process.env,
        SERENA_HOME: path.join(this.root, ".serena-data"),
        SERENA_USAGE_REPORTING: "false",
      },
    });
    this.transport.setOnDeath(() => {
      this.initializedFor = undefined;
    });
  }

  async init(cwd: string, signal?: AbortSignal): Promise<unknown> {
    if (this.initializedFor === cwd && this.transport.isAlive()) return;
    if (this.transport.isAlive()) await this.shutdown();
    await this.ensurePython();
    this.transport.start();
    const result = await this.transport.send("init", { cwd }, signal);
    this.initializedFor = cwd;
    return result;
  }

  async callTool(toolName: string, params: Record<string, unknown>, signal?: AbortSignal): Promise<unknown> {
    if (!this.initializedFor) {
      throw new Error("Bridge has not been initialized. Call init first.");
    }
    return this.transport.send("call_tool", { tool: toolName, args: params }, signal);
  }

  async shutdown(): Promise<void> {
    if (!this.transport.isAlive()) return;
    try {
      await this.transport.send("shutdown", {}, undefined, 5_000);
    } catch {
      // process may have exited before sending response — that's fine
    }
    await this.transport.shutdown();
  }

  // -- private --------------------------------------------------------------

  private async ensurePython(): Promise<void> {
    const python = localPython(this.root);
    const pip = localPip(this.root);
    const requirements = requirementsPath(this.root);

    const createdVenv = !existsSync(python);
    if (createdVenv) {
      await runSetupCommand("python3", ["-m", "venv", ".venv"], this.root);
    }

    if (createdVenv) {
      await runSetupCommand(pip, ["install", "--upgrade", "-r", requirements], this.root);
    }

    if (!existsSync(python)) {
      throw new Error(`Serena Python environment is missing. Run: ${setupCommand(this.root)}`);
    }
  }
}
