import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync } from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
  timer: NodeJS.Timeout;
};

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

const DEFAULT_TIMEOUT_MS = 240_000;

function packageRoot(): string {
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
}

function setupCommand(root: string): string {
  return `cd ${root} && python3 -m venv .venv && .venv/bin/pip install -e vendor/serena`;
}

export class SerenaBridgeClient {
  private proc: ChildProcessWithoutNullStreams | undefined;
  private nextId = 1;
  private pending = new Map<string, PendingRequest>();
  private stdoutBuffer = "";
  private stderr = "";
  private initializedFor: string | undefined;

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
    this.start();
    await this.request("init", { cwd }, signal);
    this.initializedFor = cwd;
  }

  private start(): void {
    const python = path.join(this.root, ".venv", "bin", "python");
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
        reject(new Error(`Timed out waiting for Serena bridge method ${method}. Stderr:\n${this.stderr}`));
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
