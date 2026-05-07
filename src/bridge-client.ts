import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import * as path from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
  timer: NodeJS.Timeout;
};

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

const DEFAULT_TIMEOUT_MS = 240_000;
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

function shouldRetryPythonSetup(error: unknown): boolean {
  const text = errorOutput(error);
  return text.includes("Could not import a compatible pip-installed Serena package")
    || text.includes("Python distribution serena-agent is not installed.")
    || text.includes("serena-agent") && text.includes("incompatible");
}

async function runSetupCommand(command: string, args: string[], cwd: string): Promise<void> {
  try {
    await execFileAsync(command, args, { cwd, maxBuffer: 10 * 1024 * 1024 });
  } catch (error) {
    throw new Error(`Failed to run ${commandText(command, args)} in ${cwd}:\n${errorOutput(error)}`);
  }
}

export class SerenaBridgeClient {
  private proc: ChildProcessWithoutNullStreams | undefined;
  private nextId = 1;
  private pending = new Map<string, PendingRequest>();
  private stdoutBuffer = "";
  private stderr = "";
  private initializedFor: string | undefined;
  private python: string | undefined;

  constructor(private readonly root = packageRoot()) {}

  async callTool(cwd: string, tool: string, args: Record<string, unknown>, signal?: AbortSignal): Promise<unknown> {
    await this.init(cwd, signal);
    return this.request("call_tool", { tool, args }, signal);
  }

  async listTools(cwd: string, signal?: AbortSignal): Promise<unknown> {
    await this.init(cwd, signal);
    return this.request("list_tools", {}, signal);
  }

  async shutdown(): Promise<void> {
    if (!this.proc) return;
    try {
      await this.request("shutdown", {}, undefined, 5_000);
    } catch {
      this.proc.kill();
    }
  }

  private async init(cwd: string, signal?: AbortSignal): Promise<void> {
    if (this.initializedFor === cwd && this.proc && !this.proc.killed) return;
    if (this.proc) await this.shutdown();
    await this.ensurePython();
    this.start();
    try {
      await this.request("init", { cwd }, signal);
    } catch (error) {
      if (!shouldRetryPythonSetup(error)) {
        throw error;
      }
      await this.shutdown();
      await this.ensurePython({ reinstall: true });
      this.start();
      await this.request("init", { cwd }, signal);
    }
    this.initializedFor = cwd;
  }

  private async ensurePython(options: { reinstall?: boolean } = {}): Promise<void> {
    const python = localPython(this.root);
    const pip = localPip(this.root);
    const requirements = requirementsPath(this.root);

    const createdVenv = !existsSync(python);
    if (createdVenv) {
      await runSetupCommand("python3", ["-m", "venv", ".venv"], this.root);
    }

    if (options.reinstall || createdVenv) {
      await runSetupCommand(pip, ["install", "--upgrade", "-r", requirements], this.root);
    }

    if (!existsSync(python)) {
      throw new Error(`Serena Python environment is missing. Run: ${setupCommand(this.root)}`);
    }

    this.python = python;
  }

  private start(): void {
    const python = this.python ?? localPython(this.root);
    const script = path.join(this.root, "bridge", "serena_pi_bridge.py");

    if (!existsSync(python)) {
      throw new Error(`Serena Python environment is missing. Run: ${setupCommand(this.root)}`);
    }
    if (!existsSync(script)) {
      throw new Error(`Serena bridge script is missing: ${script}`);
    }

    this.proc = spawn(python, [script], {
      cwd: this.root,
      env: {
        ...process.env,
        SERENA_HOME: path.join(this.root, ".serena-data"),
        SERENA_USAGE_REPORTING: "false",
      },
      stdio: ["pipe", "pipe", "pipe"],
    });

    this.proc.stdout.setEncoding("utf8");
    this.proc.stderr.setEncoding("utf8");
    this.proc.stdout.on("data", (chunk: string) => this.onStdout(chunk));
    this.proc.stderr.on("data", (chunk: string) => {
      this.stderr = (this.stderr + chunk).slice(-12_000);
    });
    this.proc.on("exit", (code, sig) => {
      const suffix = this.stderr ? `\nBridge stderr:\n${this.stderr}` : "";
      const err = new Error(`Serena bridge exited (${code ?? sig}).${suffix}`);
      for (const pending of this.pending.values()) {
        clearTimeout(pending.timer);
        pending.reject(err);
      }
      this.pending.clear();
      this.proc = undefined;
      this.initializedFor = undefined;
    });
  }

  private request(method: string, params: Record<string, unknown>, signal?: AbortSignal, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<unknown> {
    if (!this.proc || this.proc.killed) this.start();
    const proc = this.proc;
    if (!proc) throw new Error("Serena bridge process did not start.");
    if (signal?.aborted) return Promise.reject(new Error("aborted"));

    const id = String(this.nextId++);
    const payload = { id, method, ...params };

    return new Promise((resolve, reject) => {
      const cleanupAbort = () => signal?.removeEventListener("abort", onAbort);
      const timer = setTimeout(() => {
        cleanupAbort();
        this.pending.delete(id);
        const suffix = this.stderr ? ` Stderr:\n${this.stderr}` : "";
        reject(new Error(`Timed out waiting for Serena bridge method ${method}.${suffix}`));
        this.restartAfterTimeout();
      }, timeoutMs);
      const onAbort = () => {
        clearTimeout(timer);
        cleanupAbort();
        this.pending.delete(id);
        reject(new Error("aborted"));
      };

      this.pending.set(id, {
        resolve: (value) => {
          cleanupAbort();
          resolve(value);
        },
        reject: (err) => {
          cleanupAbort();
          reject(err);
        },
        timer,
      });
      signal?.addEventListener("abort", onAbort, { once: true });
      proc.stdin.write(`${JSON.stringify(payload)}\n`);
    });
  }

  private restartAfterTimeout(): void {
    this.initializedFor = undefined;
    if (this.proc && !this.proc.killed) {
      this.proc.kill();
    }
  }

  private onStdout(chunk: string): void {
    this.stdoutBuffer += chunk;
    for (;;) {
      const idx = this.stdoutBuffer.indexOf("\n");
      if (idx === -1) break;
      const line = this.stdoutBuffer.slice(0, idx).trim();
      this.stdoutBuffer = this.stdoutBuffer.slice(idx + 1);
      if (!line) continue;
      this.handleLine(line);
    }
  }

  private handleLine(line: string): void {
    let msg: any;
    try {
      msg = JSON.parse(line);
    } catch {
      this.stderr = (this.stderr + `\nNon-JSON stdout: ${line}`).slice(-12_000);
      return;
    }

    const pending = this.pending.get(String(msg.id));
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pending.delete(String(msg.id));

    if (msg.ok) {
      pending.resolve(msg.result);
    } else {
      pending.reject(new Error(String(msg.error ?? "Unknown Serena bridge error")));
    }
  }
}
