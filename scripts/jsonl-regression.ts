#!/usr/bin/env node
/** Regression test for the Serena bridge init/shutdown lifecycle (Issue #1)
 *  and rename_symbol tool (Issue #9). */

import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
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

/** Fixture with a uniquely-named function for rename testing. */
async function writeRenameFixture(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(path.join(fixtureRoot, "src"), { recursive: true });
  await writeFile(path.join(fixtureRoot, "package.json"), JSON.stringify({ type: "module" }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "tsconfig.json"), JSON.stringify({
    compilerOptions: { target: "ES2020", module: "ESNext", moduleResolution: "Node", strict: true },
    include: ["src/**/*.ts"],
  }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "src", "index.ts"), `export function sayHello(name: string): string {
  return \`Hello, \${name}\`;
}

export function greetAll(names: string[]): string[] {
  return names.map((n) => sayHello(n));
}
`);
}

/** Fixture with two symbols of the same name for ambiguity testing. */
async function writeAmbiguityFixture(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(path.join(fixtureRoot, "src"), { recursive: true });
  await writeFile(path.join(fixtureRoot, "package.json"), JSON.stringify({ type: "module" }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "tsconfig.json"), JSON.stringify({
    compilerOptions: { target: "ES2020", module: "ESNext", moduleResolution: "Node", strict: true },
    include: ["src/**/*.ts"],
  }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "src", "a.ts"), `export function helper(): string {
  return "a";
}
`);
  await writeFile(path.join(fixtureRoot, "src", "b.ts"), `export function helper(): string {
  return "b";
}
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

  // --- rename_symbol: successful rename ---
  await writeRenameFixture();
  await client.init(fixtureRoot);
  const renameResult = await client.callTool("rename_symbol", {
    name_path: "sayHello",
    new_name: "sayHi",
    relative_path: "src/index.ts",
  }) as string;
  console.log(`rename result: ${renameResult}`);
  assert(
    renameResult === "renamed sayHello to sayHi",
    `Expected 'renamed sayHello to sayHi', got: ${renameResult}`,
  );

  // Verify file was actually mutated
  const renamedContent = await readFile(path.join(fixtureRoot, "src", "index.ts"), "utf8");
  assert(
    renamedContent.includes("function sayHi") && renamedContent.includes("sayHi(n)"),
    `File should contain renamed symbol 'sayHi':\n${renamedContent}`,
  );
  assert(
    !renamedContent.includes("sayHello"),
    `Old name 'sayHello' should be gone:\n${renamedContent}`,
  );
  console.log(`File mutated correctly for rename.`);

  // --- rename_symbol: rename back to original name ---
  const renameBackResult = await client.callTool("rename_symbol", {
    name_path: "sayHi",
    new_name: "sayHello",
    relative_path: "src/index.ts",
  }) as string;
  console.log(`rename back result: ${renameBackResult}`);
  assert(
    renameBackResult === "renamed sayHi to sayHello",
    `Expected 'renamed sayHi to sayHello', got: ${renameBackResult}`,
  );

  const restoredContent = await readFile(path.join(fixtureRoot, "src", "index.ts"), "utf8");
  assert(
    restoredContent.includes("function sayHello") && restoredContent.includes("sayHello(n)"),
    `File should have original name 'sayHello' back:\n${restoredContent}`,
  );
  console.log(`File restored correctly.`);

  await client.shutdown();

  // --- rename_symbol: ambiguous name_path ---
  await writeAmbiguityFixture();
  await client.init(fixtureRoot);
  const ambigResult = await client.callTool("rename_symbol", {
    name_path: "helper",
    new_name: "assistant",
  }) as string;
  console.log(`ambiguity result: ${ambigResult}`);
  assert(
    ambigResult.startsWith("Error:") && ambigResult.includes("Ambiguous"),
    `Expected ambiguous error, got: ${ambigResult}`,
  );
  // Verify files were NOT mutated
  const aContent = await readFile(path.join(fixtureRoot, "src", "a.ts"), "utf8");
  const bContent = await readFile(path.join(fixtureRoot, "src", "b.ts"), "utf8");
  assert(
    aContent.includes("function helper"),
    `File a.ts should NOT have been renamed:\n${aContent}`,
  );
  assert(
    bContent.includes("function helper"),
    `File b.ts should NOT have been renamed:\n${bContent}`,
  );
  console.log(`Ambiguity correctly rejected, files unchanged.`);

  await client.shutdown();

  console.log(`PASS jsonl regression (init/shutdown + rename_symbol): ${fixtureRoot}`);
}

run().catch(async (error) => {
  console.error(`FAIL jsonl regression: ${error instanceof Error ? error.stack : error}`);
  if (client) {
    try { await client.shutdown(); } catch { /* ignore */ }
  }
  process.exitCode = 1;
});
