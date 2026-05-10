#!/usr/bin/env node
/** Regression test for the Serena bridge init/shutdown lifecycle and get_document_symbols tool (Issues #1, #4). */

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

  // --- get_document_symbols on TypeScript fixture, depth=0 ---
  const symbolsDepth0 = await client.callTool("get_document_symbols", { relative_path: "src/index.ts", depth: 0 }) as string;
  assert(typeof symbolsDepth0 === "string", `depth=0 should return a string, got ${typeof symbolsDepth0}`);
  const lines0 = symbolsDepth0.trim().split("\n");
  assert(lines0.length > 0, "depth=0 should return at least one symbol");
  // Verify format: each line is "Kind Name" with no leading spaces
  for (const line of lines0) {
    assert(/^[A-Z][a-zA-Z]+ \w+/.test(line), `depth=0 line should match "Kind Name": "${line}"`);
    assert(!line.startsWith(" "), `depth=0 line should have no indent: "${line}"`);
  }
  console.log(`get_document_symbols depth=0 OK: ${lines0.length} top-level symbol(s)`);

  // --- get_document_symbols on TypeScript fixture, depth=1 ---
  const symbolsDepth1 = await client.callTool("get_document_symbols", { relative_path: "src/index.ts", depth: 1 }) as string;
  assert(typeof symbolsDepth1 === "string", `depth=1 should return a string, got ${typeof symbolsDepth1}`);
  const lines1 = symbolsDepth1.trim().split("\n");
  assert(lines1.length >= lines0.length, "depth=1 should include at least as many lines as depth=0");
  // If there are indented lines, verify 2-space indent
  const indentedLines = lines1.filter(l => l.startsWith(" "));
  for (const line of indentedLines) {
    assert(line.startsWith("  ") && !line.startsWith("   "), `Indented line should use 2 spaces: "${line}"`);
  }
  console.log(`get_document_symbols depth=1 OK: ${lines1.length} lines (${indentedLines.length} indented)`);

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

  // --- get_document_symbols on Python fixture, depth=0 ---
  const pySymbolsDepth0 = await client.callTool("get_document_symbols", { relative_path: "test.py", depth: 0 }) as string;
  assert(typeof pySymbolsDepth0 === "string", `Python depth=0 should return a string, got ${typeof pySymbolsDepth0}`);
  const pyLines0 = pySymbolsDepth0.trim().split("\n");
  assert(pyLines0.length > 0, "Python depth=0 should return at least one symbol");
  for (const line of pyLines0) {
    assert(/^[A-Z][a-zA-Z]+ \w+/.test(line), `Python depth=0 line should match "Kind Name": "${line}"`);
    assert(!line.startsWith(" "), `Python depth=0 line should have no indent: "${line}"`);
  }
  console.log(`Python get_document_symbols depth=0 OK: ${pyLines0.length} top-level symbol(s)`);

  // --- get_document_symbols on Python fixture, depth=1 ---
  const pySymbolsDepth1 = await client.callTool("get_document_symbols", { relative_path: "test.py", depth: 1 }) as string;
  assert(typeof pySymbolsDepth1 === "string", `Python depth=1 should return a string, got ${typeof pySymbolsDepth1}`);
  const pyLines1 = pySymbolsDepth1.trim().split("\n");
  assert(pyLines1.length >= pyLines0.length, "Python depth=1 should include at least as many lines as depth=0");
  console.log(`Python get_document_symbols depth=1 OK: ${pyLines1.length} lines`);

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

  console.log(`PASS jsonl regression (init/shutdown + get_document_symbols): ${fixtureRoot}`);
}

run().catch(async (error) => {
  console.error(`FAIL jsonl regression: ${error instanceof Error ? error.stack : error}`);
  if (client) {
    try { await client.shutdown(); } catch { /* ignore */ }
  }
  process.exitCode = 1;
});
