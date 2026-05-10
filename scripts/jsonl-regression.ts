#!/usr/bin/env node
/** Regression test for the Serena bridge init/shutdown lifecycle (Issue #1)
 * and get_implementations tool (Issue #7). */

import { mkdir, rm, writeFile } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { SerenaBridgeClient } from "../src/bridge-client.js";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fixtureRoot = path.join(os.tmpdir(), `pi-serena-lsp-jsonl-${process.pid}`);

let client: SerenaBridgeClient;

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

async function writeTypeScriptFixture(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(path.join(fixtureRoot, "src"), { recursive: true });
  await writeFile(path.join(fixtureRoot, "package.json"), JSON.stringify({ type: "module" }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "tsconfig.json"), JSON.stringify({
    compilerOptions: { target: "ES2020", module: "ESNext", moduleResolution: "Node", strict: true },
    include: ["src/**/*.ts"],
  }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "src", "index.ts"), `export function greet(name: string): string {
  return \`Hello, \${name}\`;
}

export interface Greeter {
  greet(name: string): string;
}

export class FriendlyGreeter implements Greeter {
  greet(name: string): string {
    return \`Hi there, \${name}!\`;
  }
}
`);
}

async function writePythonFixture(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(fixtureRoot, { recursive: true });
  await writeFile(path.join(fixtureRoot, "test.py"), `def greet(name: str) -> str:
    return f"Hello, {name}"

class Greeter:
    def greet(self, name: str) -> str:
        raise NotImplementedError

class FriendlyGreeter(Greeter):
    def greet(self, name: str) -> str:
        return f"Hi there, {name}!"
`);
}

async function run(): Promise<void> {
  client = new SerenaBridgeClient();

  // --- TypeScript fixture: init + shutdown ---
  await writeTypeScriptFixture();
  const tsResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(tsResult.ok === true, `TypeScript init should succeed: ${JSON.stringify(tsResult)}`);
  assert(typeof tsResult.language === "string", `Should return language: ${JSON.stringify(tsResult)}`);
  assert(typeof tsResult.cwd === "string", `Should return cwd: ${JSON.stringify(tsResult)}`);
  console.log(`TypeScript init OK: language=${tsResult.language}`);

  await client.shutdown();

  // --- Re-init same project ---
  const tsResult2 = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(tsResult2.ok === true, `TypeScript re-init should succeed: ${JSON.stringify(tsResult2)}`);

  await client.shutdown();

  // --- Python fixture: init + shutdown (with .serenaproject.yml) ---
  await writePythonFixture();
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - python\n",
  );
  const pyResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(pyResult.ok === true, `Python init should succeed: ${JSON.stringify(pyResult)}`);
  assert(pyResult.language === "python", `Should be python from config: ${JSON.stringify(pyResult)}`);
  console.log(`Python init OK: language=${pyResult.language}`);

  await client.shutdown();

  // --- Init with .serenaproject.yml (TypeScript) ---
  await writeTypeScriptFixture();
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - typescript\n",
  );
  const cfgResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(cfgResult.ok === true, `.serenaproject.yml init should succeed: ${JSON.stringify(cfgResult)}`);
  assert(cfgResult.language === "typescript", `Should be typescript from config: ${JSON.stringify(cfgResult)}`);

  await client.shutdown();

  // -----------------------------------------------------------------------
  // get_implementations: successful implementation lookup (TypeScript)
  // -----------------------------------------------------------------------

  await writeTypeScriptFixture();
  const tsImplInit = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(tsImplInit.ok === true, `TS init for impl test should succeed: ${JSON.stringify(tsImplInit)}`);

  const implResult = await client.callTool("get_implementations", {
    name_path: "Greeter/greet",
  }) as Record<string, unknown>;

  assert(
    implResult && typeof implResult === "object" && "symbols" in implResult,
    `get_implementations should return symbols: ${JSON.stringify(implResult)}`,
  );

  const symbols = (implResult as Record<string, unknown>).symbols as Array<Record<string, unknown>>;
  assert(Array.isArray(symbols) && symbols.length > 0, "Should have at least one implementing symbol");

  const implSymbol = symbols[0];
  assert(typeof implSymbol.name_path === "string", "Implementation should have name_path");
  assert(typeof implSymbol.kind === "string", "Implementation should have kind");
  assert(typeof implSymbol.location === "string", "Implementation should have location");
  console.log(`get_implementations OK: found ${symbols.length} implementing symbol(s) for Greeter/greet`);
  console.log(`  name_path=${implSymbol.name_path} kind=${implSymbol.kind} location=${implSymbol.location}`);

  await client.shutdown();

  // -----------------------------------------------------------------------
  // get_implementations: graceful error when LS doesn't support the method
  // (Python LS does not support textDocument/implementation)
  // -----------------------------------------------------------------------

  await writePythonFixture();
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - python\n",
  );
  const pyImplInit = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(pyImplInit.ok === true, `Python init for impl test should succeed: ${JSON.stringify(pyImplInit)}`);

  const pyImplResult = await client.callTool("get_implementations", {
    name_path: "Greeter/greet",
  }) as Record<string, unknown>;

  // Python LS doesn't support textDocument/implementation — should get a graceful error
  assert(
    pyImplResult && typeof pyImplResult === "object" && "error" in pyImplResult,
    `Python get_implementations should return graceful error: ${JSON.stringify(pyImplResult)}`,
  );
  console.log(`get_implementations graceful error OK: ${(pyImplResult as Record<string, unknown>).error}`);

  await client.shutdown();

  console.log(`PASS jsonl regression (init/shutdown + get_implementations): ${fixtureRoot}`);
}

run().catch(async (error) => {
  console.error(`FAIL jsonl regression: ${error instanceof Error ? error.stack : error}`);
  if (client) {
    try { await client.shutdown(); } catch { /* ignore */ }
  }
  process.exitCode = 1;
});
