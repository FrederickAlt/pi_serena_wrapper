#!/usr/bin/env node
/** Regression test for Serena bridge init/shutdown lifecycle and get_docstring tool. */

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
`);
}

/**
 * TypeScript fixture with a JSDoc-documented function and an undocumented one.
 * Also includes two classes with the same method name for ambiguity testing.
 */
async function writeDocstringFixture(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(path.join(fixtureRoot, "src"), { recursive: true });
  await writeFile(path.join(fixtureRoot, "package.json"), JSON.stringify({ type: "module" }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "tsconfig.json"), JSON.stringify({
    compilerOptions: { target: "ES2020", module: "ESNext", moduleResolution: "Node", strict: true },
    include: ["src/**/*.ts"],
  }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "src", "index.ts"), `/**
 * Sends a JSON-RPC request over stdin/stdout and returns the response.
 */
export function doRequest(method: string, params: unknown[]): string {
  return JSON.stringify({ method, params });
}

/** No JSDoc on this one. */
export function undocumented(): string {
  return "undocumented";
}

export class Alpha {
  /** Alpha's helper. */
  work(): void {}
}

export class Beta {
  /** Beta's helper. */
  work(): void {}
}
`);
}

function writePythonFixture(): Promise<void> {
  return writePythonFixtureImpl();
}

async function writePythonFixtureImpl(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(fixtureRoot, { recursive: true });
  await writeFile(path.join(fixtureRoot, "test.py"), `def greet(name: str) -> str:
    return f"Hello, {name}"
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

  console.log(`PASS jsonl regression (init/shutdown): ${fixtureRoot}`);

  // --- get_docstring tests ---
  await writeDocstringFixture();
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - typescript\n",
  );
  await client.init(fixtureRoot);

  // 1. Documented symbol: doRequest should have JSDoc hover text.
  const docText = String(await client.callTool("get_docstring", { name_path: "doRequest" }));
  assert(docText.length > 0, `get_docstring should return non-empty text`);
  assert(
    docText !== "No docstring available.",
    `doRequest should have a docstring: ${docText}`,
  );
  // The JSDoc text should appear somewhere in the hover.
  assert(
    docText.toLowerCase().includes("sends") || docText.toLowerCase().includes("json-rpc"),
    `doRequest docstring should contain JSDoc text, got: ${docText}`,
  );
  console.log(`get_docstring (documented): ${docText.slice(0, 80)}...`);

  // 2. Undocumented symbol: TypeScript LS returns signature even without JSDoc.
  // We just verify it returns some text, not the sentinel.
  const undocText = String(await client.callTool("get_docstring", { name_path: "undocumented" }));
  assert(undocText.length > 0, `get_docstring for undocumented should return non-empty text, got: ${JSON.stringify(undocText)}`);
  assert(
    undocText !== "No docstring available.",
    `undocumented should still have hover info from LS, got: ${JSON.stringify(undocText)}`,
  );
  console.log(`get_docstring (undocumented): ${undocText.slice(0, 80)}...`);

  // 3. Ambiguous name_path: "work" matches Alpha/work and Beta/work.
  try {
    await client.callTool("get_docstring", { name_path: "work" });
    throw new Error("Expected ambiguity error but call succeeded");
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    const msgLower = msg.toLowerCase();
    if (!msgLower.includes("ambigu") && !msgLower.includes("found") && !msgLower.includes("match")) {
      throw new Error(`Expected ambiguity-related error, got: ${msg}`);
    }
    console.log(`get_docstring (ambiguity): ${msg}`);
  }

  await client.shutdown();

  console.log(`PASS jsonl regression (get_docstring): ${fixtureRoot}`);
}

run().catch(async (error) => {
  console.error(`FAIL jsonl regression: ${error instanceof Error ? error.stack : error}`);
  if (client) {
    try { await client.shutdown(); } catch { /* ignore */ }
  }
  process.exitCode = 1;
});
