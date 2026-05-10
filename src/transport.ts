import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync } from "node:fs";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
  timer: NodeJS.Timeout;
};

export const DEFAULT_TIMEOUT_MS = 240_000;

// ---------------------------------------------------------------------------
// Interface
// ---------------------------------------------------------------------------

export interface JsonRpcTransport {
  /** Send a JSON-RPC request and await the response. */
  send(
    method: string,
    params: Record<string, unknown>,
    signal?: AbortSignal,
    timeoutMs?: number,
  ): Promise<unknown>;

  /** Whether the child process is currently alive. */
  isAlive(): boolean;

  /** Kill the child process and clean up. No-op if already dead. */
  shutdown(timeoutMs?: number): Promise<void>;

  /** Accumulated stderr output (last 12 000 chars), accessible for error messages. */
  readonly stderr: string;

  /** Spawn the child process. Throws if python or script are missing. */
  start(): void;

  /** Register a callback invoked when the process exits (for any reason). */
  setOnDeath(cb: () => void): void;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

export class SubprocessTransport implements JsonRpcTransport {
  private proc: ChildProcessWithoutNullStreams | undefined;
  private nextId = 1;
  private pending = new Map<string, PendingRequest>();
  private stdoutBuffer = "";
  private _stderr = "";
  private onDeathCallback: (() => void) | undefined;
  private _shuttingDown = false;

  constructor(
    private readonly python: string,
    private readonly script: string,
    private readonly options: { cwd?: string; env?: NodeJS.ProcessEnv } = {},
  ) {}

  setOnDeath(cb: () => void): void {
    this.onDeathCallback = cb;
  }

  get stderr(): string {
    return this._stderr;
  }

  isAlive(): boolean {
    return !!this.proc && !this.proc.killed;
  }

  start(): void {
    if (!existsSync(this.python)) {
      throw new Error(`Serena Python environment is missing. Run: cd ${this.options.cwd} && python3 -m venv .venv && .venv/bin/pip install --upgrade -r requirements.txt`);
    }
    if (!existsSync(this.script)) {
      throw new Error(`Serena bridge script is missing: ${this.script}`);
    }

    this.proc = spawn(this.python, [this.script], {
      cwd: this.options.cwd,
      env: this.options.env,
      stdio: ["pipe", "pipe", "pipe"],
    });

    this.proc.stdout.setEncoding("utf8");
    this.proc.stderr.setEncoding("utf8");
    this.proc.stdout.on("data", (chunk: string) => this.onStdout(chunk));
    this.proc.stderr.on("data", (chunk: string) => {
      this._stderr = (this._stderr + chunk).slice(-12_000);
    });
    this.proc.on("exit", (code, sig) => {
      if (!this._shuttingDown) {
        const suffix = this._stderr ? `\nBridge stderr:\n${this._stderr}` : "";
        const err = new Error(`Serena bridge exited (${code ?? sig}).${suffix}`);
        for (const pending of this.pending.values()) {
          clearTimeout(pending.timer);
          pending.reject(err);
        }
        this.pending.clear();
      }
      this.proc = undefined;
      this._shuttingDown = false;
      this.onDeathCallback?.();
    });
  }

  async send(
    method: string,
    params: Record<string, unknown>,
    signal?: AbortSignal,
    timeoutMs = DEFAULT_TIMEOUT_MS,
  ): Promise<unknown> {
    if (!this.isAlive()) this.start();
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
        const suffix = this._stderr ? ` Stderr:\n${this._stderr}` : "";
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

  async shutdown(timeoutMs = 5_000): Promise<void> {
    if (!this.isAlive()) return;
    this._shuttingDown = true;
    const proc = this.proc!;
    proc.kill();
    // Wait briefly for the process to exit, but don't block indefinitely.
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, timeoutMs);
      proc.once("exit", () => {
        clearTimeout(timer);
        resolve();
      });
    });
  }

  // -- internal helpers -----------------------------------------------------

  private restartAfterTimeout(): void {
    this.onDeathCallback?.();
    if (this.proc && !this.proc.killed) this.proc.kill();
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
    let msg: unknown;
    try {
      msg = JSON.parse(line);
    } catch {
      this._stderr = (this._stderr + `\nNon-JSON stdout: ${line}`).slice(-12_000);
      return;
    }

    if (msg === null || typeof msg !== "object") return;
    const response = msg as Record<string, unknown>;
    const pending = this.pending.get(String(response.id));
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pending.delete(String(response.id));

    if (response.ok) {
      pending.resolve(response.result);
    } else {
      const errorMessage =
        typeof response.error === "object" && response.error !== null && "message" in response.error
          ? String((response.error as Record<string, unknown>).message)
          : String(response.error ?? "Unknown Serena bridge error");
      pending.reject(new Error(errorMessage));
    }
  }
}
