#!/usr/bin/env node
import { spawn } from "node:child_process";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fixtureRoot = path.join(os.tmpdir(), `pi-serena-lsp-jsonl-${process.pid}`);
const failedToolLog = path.join(packageRoot, ".serena-data", "failed-tool-calls.jsonl");
const expectedTools = [
  "get_symbols_overview",
  "find_symbol",
  "find_referencing_symbols",
  "find_declaration",
  "find_type_definition",
  "find_implementations",
  "rename_symbol",
];
const removedTools = ["get_diagnostics_for_file", "get_diagnostics_for_symbol"];

let nextId = 1;
let proc;
let stdout = "";
let stderr = "";
const pending = new Map();

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function stringify(value) {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

async function writeFixture() {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(path.join(fixtureRoot, "src"), { recursive: true });
  await writeFile(path.join(fixtureRoot, "package.json"), JSON.stringify({ type: "module" }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "tsconfig.json"), JSON.stringify({
    compilerOptions: {
      target: "ES2020",
      module: "ESNext",
      moduleResolution: "Node",
      strict: true,
    },
    include: ["src/**/*.ts"],
  }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "src", "index.ts"), `export interface Runner {
  run(input: string): string;
}

export class Greeter {
  greet(name: string): string {
    return \`Hello, \${name}\`;
  }
}

export function makeGreeting(name: string): string {
  const greeter = new Greeter();
  return greeter.greet(name);
}
`);
  await writeFile(path.join(fixtureRoot, "src", "usage.ts"), `import { Greeter, makeGreeting } from "./index";

export function useGreeting(): string {
  const greeter = new Greeter();
  const namedGreeter: Greeter = greeter;
  return greeter.greet("World") + makeGreeting("Serena");
}
`);
  await writeFile(path.join(fixtureRoot, "src", "implementation.ts"), `import type { Runner } from "./index";

export class ConcreteRunner implements Runner {
  run(input: string): string {
    return input.toUpperCase();
  }
}
`);
  await writeFile(path.join(fixtureRoot, "src", "rename-target.ts"), `export function renameMe(value: string): string {
  return value.trim();
}
`);
  await writeFile(path.join(fixtureRoot, "src", "rename-consumer.ts"), `import { renameMe } from "./rename-target";

export const renamedValue = renameMe("  value  ");
`);
}

async function writePythonFixture() {
  await mkdir(path.join(fixtureRoot, "py"), { recursive: true });
  await writeFile(path.join(fixtureRoot, "py", "test.py"), `from typing import Protocol

class MyInterface(Protocol):
    def foo(self) -> str:
        ...

class MyRenamed:
    def foo(self) -> str:
        return "ok"

obj = MyRenamed()
obj.foo()
`);
}

function startBridge() {
  stdout = "";
  stderr = "";
  pending.clear();
  const python = path.join(packageRoot, ".venv", "bin", "python");
  const script = path.join(packageRoot, "bridge", "serena_pi_bridge.py");
  if (!existsSync(python)) {
    throw new Error(`Missing Python environment. Run: cd ${packageRoot} && python3 -m venv .venv && .venv/bin/pip install --upgrade serena-agent`);
  }
  proc = spawn(python, [script], {
    cwd: packageRoot,
    env: {
      ...process.env,
      SERENA_HOME: path.join(packageRoot, ".serena-data"),
      SERENA_USAGE_REPORTING: "false",
    },
    stdio: ["pipe", "pipe", "pipe"],
  });
  proc.stdout.setEncoding("utf8");
  proc.stderr.setEncoding("utf8");
  proc.stdout.on("data", (chunk) => {
    stdout += chunk;
    for (;;) {
      const idx = stdout.indexOf("\n");
      if (idx === -1) break;
      const line = stdout.slice(0, idx).trim();
      stdout = stdout.slice(idx + 1);
      if (line) handleLine(line);
    }
  });
  proc.stderr.on("data", (chunk) => {
    stderr = (stderr + chunk).slice(-12000);
  });
  proc.on("exit", (code, signal) => {
    const error = new Error(`Bridge exited (${code ?? signal}).\n${stderr}`);
    for (const request of pending.values()) {
      clearTimeout(request.timer);
      if (code === 0) {
        request.resolve(undefined);
      } else {
        request.reject(error);
      }
    }
    pending.clear();
  });
}

async function stopBridge() {
  if (!proc || proc.killed) return;
  try {
    await request("shutdown", {}, 5000);
  } catch (error) {
    if (!String(error.message).includes("Bridge exited (0)")) {
      throw error;
    }
  } finally {
    proc = undefined;
  }
}

function handleLine(line) {
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    stderr = (stderr + `\nNon-JSON stdout: ${line}`).slice(-12000);
    return;
  }
  const request = pending.get(String(message.id));
  if (!request) return;
  clearTimeout(request.timer);
  pending.delete(String(message.id));
  if (message.ok) {
    request.resolve(message.result);
  } else {
    request.reject(new Error(String(message.error ?? "Unknown bridge error")));
  }
}

function request(method, params = {}, timeoutMs = 240000) {
  const id = String(nextId++);
  const payload = { id, method, ...params };
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`Timed out waiting for ${method}.\n${stderr}`));
    }, timeoutMs);
    pending.set(id, { resolve, reject, timer });
    proc.stdin.write(`${JSON.stringify(payload)}\n`);
  });
}

async function expectUnknownTool(tool) {
  try {
    await request("call_tool", { tool, args: {} });
  } catch (error) {
    assert(String(error.message).includes("Unknown Serena pi tool"), `${tool} should be rejected as unknown`);
    return;
  }
  throw new Error(`${tool} unexpectedly succeeded`);
}

async function run() {
  await writeFixture();
  await writePythonFixture();
  await rm(failedToolLog, { force: true });
  startBridge();

  await request("init", { cwd: fixtureRoot });
  const tools = await request("list_tools");
  assert(JSON.stringify(tools) === JSON.stringify(expectedTools), `Unexpected tools: ${JSON.stringify(tools)}`);
  for (const removedTool of removedTools) {
    assert(!tools.includes(removedTool), `${removedTool} should not be exposed`);
    await expectUnknownTool(removedTool);
  }

  const overview = stringify(await request("call_tool", {
    tool: "get_symbols_overview",
    args: { relative_path: "src/index.ts", depth: 1 },
  }));
  assert(overview.includes("Greeter") && overview.includes("makeGreeting") && overview.includes("Runner"), overview);

  const symbol = stringify(await request("call_tool", {
    tool: "find_symbol",
    args: { relative_path: "src/index.ts", name_path_pattern: "Greeter", depth: 1, include_body: true },
  }));
  assert(symbol.includes("Greeter") && symbol.includes("greet"), symbol);

  const references = stringify(await request("call_tool", {
    tool: "find_referencing_symbols",
    args: { relative_path: "src/index.ts", name_path: "Greeter/greet" },
  }));
  assert(references.includes("src/usage.ts") || references.includes("useGreeting"), references);

  const declaration = stringify(await request("call_tool", {
    tool: "find_declaration",
    args: { relative_path: "src/usage.ts", code_snippet: '.greet("World")', symbol_text: "greet", include_body: true },
  }));
  assert(declaration.includes("src/index.ts") && declaration.includes("greet"), declaration);

  try {
    await request("call_tool", {
      tool: "find_declaration",
      args: { relative_path: "src/usage.ts", code_snippet: "makeGreeting", symbol_text: "makeGreeting" },
    });
    throw new Error("Ambiguous find_declaration unexpectedly succeeded");
  } catch (error) {
    assert(String(error.message).includes("Expected code_snippet to match exactly once"), String(error.message));
  }

  const failureLog = await readFile(failedToolLog, "utf8");
  const failureEntries = failureLog.trim().split("\n").map((line) => JSON.parse(line));
  assert(failureEntries.length === 1, `Expected one failed tool log entry, got ${failureEntries.length}: ${failureLog}`);
  assert(failureEntries[0].tool === "find_declaration", JSON.stringify(failureEntries[0]));
  assert(failureEntries[0].failure_kind === "exception", JSON.stringify(failureEntries[0]));
  assert(failureEntries[0].args.code_snippet === "makeGreeting", JSON.stringify(failureEntries[0]));

  const declarationByOccurrence = stringify(await request("call_tool", {
    tool: "find_declaration",
    args: { relative_path: "src/usage.ts", code_snippet: "makeGreeting", symbol_text: "makeGreeting", occurrence_index: 1 },
  }));
  assert(declarationByOccurrence.includes("src/index.ts") && declarationByOccurrence.includes("makeGreeting"), declarationByOccurrence);

  const typeDefinition = stringify(await request("call_tool", {
    tool: "find_type_definition",
    args: { relative_path: "src/usage.ts", code_snippet: "namedGreeter: Greeter", symbol_text: "namedGreeter", include_body: true },
  }));
  assert(typeDefinition.includes("Greeter") && typeDefinition.includes("src/index.ts"), typeDefinition);

  const implementations = stringify(await request("call_tool", {
    tool: "find_implementations",
    args: { relative_path: "src/index.ts", name_path: "Runner/run", include_body: true },
  }));
  assert(implementations.includes("ConcreteRunner") || implementations.includes("src/implementation.ts"), implementations);

  const rename = stringify(await request("call_tool", {
    tool: "rename_symbol",
    args: { relative_path: "src/rename-target.ts", name_path: "renameMe", new_name: "renamedBySerena" },
  }));
  const renamedTarget = await readFile(path.join(fixtureRoot, "src", "rename-target.ts"), "utf8");
  assert(rename.includes("renamedBySerena") || renamedTarget.includes("renamedBySerena"), rename);
  assert(renamedTarget.includes("renamedBySerena") && !renamedTarget.includes("renameMe"), renamedTarget);

  await stopBridge();

  startBridge();
  await request("init", { cwd: path.join(fixtureRoot, "py") });
  const unsupportedImplementations = stringify(await request("call_tool", {
    tool: "find_implementations",
    args: { relative_path: "test.py", name_path: "MyInterface" },
  }));
  assert(unsupportedImplementations.includes("not supported by the active language server"), unsupportedImplementations);
  assert(!unsupportedImplementations.includes("Traceback"), unsupportedImplementations);

  const finalFailureLog = await readFile(failedToolLog, "utf8");
  const finalFailureEntries = finalFailureLog.trim().split("\n").map((line) => JSON.parse(line));
  assert(finalFailureEntries.length === 2, `Expected two failed tool log entries, got ${finalFailureEntries.length}: ${finalFailureLog}`);
  assert(finalFailureEntries[1].tool === "find_implementations", JSON.stringify(finalFailureEntries[1]));
  assert(finalFailureEntries[1].failure_kind === "error_result", JSON.stringify(finalFailureEntries[1]));

  await stopBridge();
  console.log(`PASS jsonl regression fixture: ${fixtureRoot}`);
}

run().catch(async (error) => {
  console.error(`FAIL jsonl regression: ${error.stack || error}`);
  if (stderr) console.error(`Bridge stderr:\n${stderr}`);
  if (proc && !proc.killed) proc.kill();
  process.exitCode = 1;
});
