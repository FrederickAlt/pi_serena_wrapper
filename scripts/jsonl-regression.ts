#!/usr/bin/env node
/** Regression test for the Serena bridge lifecycle and get_references tool (Issues #1, #6). */

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

async function writeTypeScriptFixtureWithReferences(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(path.join(fixtureRoot, "src"), { recursive: true });
  await writeFile(path.join(fixtureRoot, "package.json"), JSON.stringify({ type: "module" }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "tsconfig.json"), JSON.stringify({
    compilerOptions: { target: "ES2020", module: "ESNext", moduleResolution: "Node", strict: true },
    include: ["src/**/*.ts"],
  }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "src", "index.ts"), `export class Greeter {
  greet(name: string): string {
    return \`Hello, \${name}\`;
  }
}
`);
  await writeFile(path.join(fixtureRoot, "src", "caller.ts"), `import { Greeter } from "./index";

const g = new Greeter();
const msg = g.greet("world");
console.log(msg);
`);
}

async function writePythonFixture(): Promise<void> {
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

  // --- get_references tool ---
  await writeTypeScriptFixtureWithReferences();
  const refResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(refResult.ok === true, `TypeScript init for references should succeed: ${JSON.stringify(refResult)}`);

  const references = await client.callTool("get_references", {
    name_path: "Greeter/greet",
  }) as Array<Record<string, unknown>>;

  assert(Array.isArray(references), `get_references should return an array: ${JSON.stringify(references)}`);
  assert(references.length >= 2, `Expected at least 2 references (declaration + caller): got ${references.length}`);

  for (const ref of references) {
    assert(typeof ref.name_path === "string", `ref.name_path should be a string: ${JSON.stringify(ref)}`);
    assert(typeof ref.kind === "string", `ref.kind should be a string: ${JSON.stringify(ref)}`);
    assert(typeof ref.location === "string", `ref.location should be a string: ${JSON.stringify(ref)}`);
    assert(ref.location.includes(":"), `ref.location should contain ':' (file:lines): ${JSON.stringify(ref)}`);
  }

  console.log(`get_references OK: ${references.length} references found`);
  for (const ref of references) {
    console.log(`  ${ref.name_path} (${ref.kind}) at ${ref.location}`);
  }

  // --- get_references with relative_path scoping ---
  const scopedRefs = await client.callTool("get_references", {
    name_path: "Greeter/greet",
    relative_path: "src/caller.ts",
  }) as Array<Record<string, unknown>>;
  assert(Array.isArray(scopedRefs), `Scoped get_references should return an array: ${JSON.stringify(scopedRefs)}`);
  // When scoped to caller.ts, should find at least the usage there
  assert(scopedRefs.length >= 1, `Expected at least 1 reference scoped to caller.ts: got ${scopedRefs.length}`);
  console.log(`get_references with relative_path OK: ${scopedRefs.length} references found`);

  await client.shutdown();

  console.log(`PASS jsonl regression: ${fixtureRoot}`);
}

run().catch(async (error) => {
  console.error(`FAIL jsonl regression: ${error instanceof Error ? error.stack : error}`);
  if (client) {
    try { await client.shutdown(); } catch { /* ignore */ }
  }
  process.exitCode = 1;
});
