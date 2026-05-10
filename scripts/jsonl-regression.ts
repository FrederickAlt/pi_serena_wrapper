#!/usr/bin/env node
/**
 * Regression test for the Serena bridge init/shutdown lifecycle (Issue #1),
 * find_symbol tool (Issue #3), and get_document_symbols tool (Issue #4).
 */

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

interface FindSymbolResult {
  symbols: Array<{ name_path: string; kind: string; location: string }>;
  truncated: boolean;
}

// -- fixtures --------------------------------------------------------------

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

/** Richer fixture with a class, methods, and a standalone function. */
async function writeRichTypeScriptFixture(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(path.join(fixtureRoot, "src"), { recursive: true });
  await mkdir(path.join(fixtureRoot, "src", "lib"), { recursive: true });
  await writeFile(path.join(fixtureRoot, "package.json"), JSON.stringify({ type: "module" }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "tsconfig.json"), JSON.stringify({
    compilerOptions: { target: "ES2020", module: "ESNext", moduleResolution: "Node", strict: true },
    include: ["src/**/*.ts"],
  }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "src", "index.ts"), [
    "export class MyClass {",
    "  greet(name: string): string {",
    "    return `Hello, ${name}`;",
    "  }",
    "",
    "  send(data: string): void {",
    "    console.log(data);",
    "  }",
    "}",
    "",
    "export function helper(): void {",
    "  console.log('helper');",
    "}",
    "",
  ].join("\n") + "\n");
  // Second file in a subdirectory
  await writeFile(path.join(fixtureRoot, "src", "lib", "utils.ts"), [
    "export class AnotherClass {",
    "  process(data: string): string {",
    "    return data.toUpperCase();",
    "  }",
    "}",
    "",
  ].join("\n") + "\n");
}

async function writePythonFixture(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(fixtureRoot, { recursive: true });
  await writeFile(path.join(fixtureRoot, "test.py"), `def greet(name: str) -> str:
    return f"Hello, {name}"
`);
}

// -- helpers ---------------------------------------------------------------

function findSymbol(
  symbols: Array<{ name_path: string; kind: string; location: string }>,
  namePath: string,
) {
  return symbols.find((s) => s.name_path === namePath);
}

// -- tests -----------------------------------------------------------------

async function testInitShutdown(): Promise<void> {
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
  console.log(`TypeScript cfg init OK: language=${cfgResult.language}`);

  await client.shutdown();
}

async function testFindSymbolBasic(): Promise<void> {
  await writeRichTypeScriptFixture();
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - typescript\n",
  );
  const initResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(initResult.ok === true, `Init should succeed: ${JSON.stringify(initResult)}`);

  // 1. find_symbol with just name_path — returns matching symbols project-wide
  const result1 = await client.callTool("find_symbol", { name_path: "MyClass" }) as FindSymbolResult;
  assert(Array.isArray(result1.symbols), "symbols should be an array");
  assert(result1.symbols.length >= 1, `Expected at least 1 match for MyClass, got ${result1.symbols.length}`);
  const mc = findSymbol(result1.symbols, "MyClass");
  assert(mc !== undefined, "MyClass should be in results");
  assert(mc.kind === "Class", `MyClass kind should be Class, got ${mc.kind}`);
  assert(mc.location.includes("src/index.ts"), `Location should include src/index.ts, got ${mc.location}`);
  console.log(`find_symbol name_path only OK: ${result1.symbols.length} matches`);

  // 2. find_symbol for a method (nested name path)
  const result2 = await client.callTool("find_symbol", { name_path: "MyClass/greet" }) as FindSymbolResult;
  assert(Array.isArray(result2.symbols), "symbols should be an array");
  const greet = findSymbol(result2.symbols, "MyClass/greet");
  assert(greet !== undefined, "MyClass/greet should be in results");
  assert(greet.kind === "Method", `MyClass/greet kind should be Method, got ${greet.kind}`);
  console.log(`find_symbol nested name_path OK: ${result2.symbols.length} matches`);

  // 2b. find_symbol with just last component (pattern match)
  const result2b = await client.callTool("find_symbol", { name_path: "send" }) as FindSymbolResult;
  assert(Array.isArray(result2b.symbols), "symbols should be an array");
  // "send" should match MyClass/send
  const sendMatch = result2b.symbols.find((s) => s.name_path.endsWith("/send") || s.name_path === "send");
  assert(sendMatch !== undefined, "send should match MyClass/send via pattern");
  console.log(`find_symbol single-component pattern OK: ${result2b.symbols.length} matches`);

  // 2c. find_symbol with absolute (leading /) name path
  const result2c = await client.callTool("find_symbol", { name_path: "/MyClass/greet" }) as FindSymbolResult;
  assert(Array.isArray(result2c.symbols), "symbols should be an array");
  // With exact match, should also find MyClass/greet
  const exactMatch = findSymbol(result2c.symbols, "MyClass/greet");
  assert(exactMatch !== undefined, "/MyClass/greet should exactly match MyClass/greet");
  console.log(`find_symbol absolute name_path OK: ${result2c.symbols.length} matches`);

  // 3. find_symbol with relative_path scoped to src/lib
  const result3 = await client.callTool("find_symbol", {
    name_path: "AnotherClass",
    relative_path: "src/lib",
  }) as FindSymbolResult;
  assert(result3.symbols.length >= 1, `Expected AnotherClass in src/lib, got ${result3.symbols.length}`);
  const ac = findSymbol(result3.symbols, "AnotherClass");
  assert(ac !== undefined, "AnotherClass should be in scoped results");
  assert(ac.location.includes("src/lib"), `Location should be in src/lib, got ${ac.location}`);
  console.log(`find_symbol with relative_path OK: ${result3.symbols.length} matches`);

  // 4. find_symbol with kinds filter
  const result4 = await client.callTool("find_symbol", {
    name_path: "MyClass",
    kinds: [5],  // Class = 5
  }) as FindSymbolResult;
  assert(result4.symbols.length >= 1, "kinds filter [5] should include MyClass");
  for (const s of result4.symbols) {
    assert(s.kind === "Class", `All results should be Class, got ${s.kind}`);
  }
  console.log(`find_symbol kinds filter OK: ${result4.symbols.length} matches`);

  // 5. find_symbol with max_matches and truncated
  const result5 = await client.callTool("find_symbol", {
    name_path: "MyClass",
    max_matches: 1,
  }) as FindSymbolResult;
  assert(result5.symbols.length === 1, `max_matches=1 should cap at 1, got ${result5.symbols.length}`);
  assert(result5.truncated === false || result5.truncated === true, "truncated should be boolean");
  console.log(`find_symbol max_matches OK: ${result5.symbols.length} matches, truncated=${result5.truncated}`);

  await client.shutdown();
}

async function testFindSymbolWithSnippet(): Promise<void> {
  await writeRichTypeScriptFixture();
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - typescript\n",
  );
  const initResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(initResult.ok === true, `Init should succeed: ${JSON.stringify(initResult)}`);

  // 6. find_symbol with code_snippet (project-wide) — "console.log" appears in send()
  const result6 = await client.callTool("find_symbol", {
    name_path: "MyClass/send",
    code_snippet: "console.log",
  }) as FindSymbolResult;
  assert(Array.isArray(result6.symbols), "symbols should be an array");
  console.log(`find_symbol with code_snippet project-wide OK: ${result6.symbols.length} matches`);

  // 7. find_symbol with code_snippet and relative_path
  const result7 = await client.callTool("find_symbol", {
    name_path: "MyClass/send",
    code_snippet: "console.log",
    relative_path: "src",
  }) as FindSymbolResult;
  assert(Array.isArray(result7.symbols), "symbols should be an array");
  console.log(`find_symbol with code_snippet + relative_path OK: ${result7.symbols.length} matches`);

  // 8. find_symbol with code_snippet and kinds
  const result8 = await client.callTool("find_symbol", {
    name_path: "MyClass/send",
    code_snippet: "console.log",
    kinds: [6],  // Method = 6
  }) as FindSymbolResult;
  assert(Array.isArray(result8.symbols), "symbols should be an array");
  for (const s of result8.symbols) {
    assert(s.kind === "Method", `All results should be Method, got ${s.kind}`);
  }
  console.log(`find_symbol with code_snippet + kinds OK: ${result8.symbols.length} matches`);

  await client.shutdown();
}

async function testFindSymbolOutputFormat(): Promise<void> {
  await writeRichTypeScriptFixture();
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - typescript\n",
  );
  const initResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(initResult.ok === true, `Init should succeed: ${JSON.stringify(initResult)}`);

  const result = await client.callTool("find_symbol", { name_path: "MyClass" }) as FindSymbolResult;
  assert(typeof result.truncated === "boolean", "truncated should be boolean");
  assert(Array.isArray(result.symbols), "symbols should be an array");
  for (const sym of result.symbols) {
    assert(typeof sym.name_path === "string", "name_path should be string");
    assert(typeof sym.kind === "string", "kind should be string");
    assert(typeof sym.location === "string", "location should be string");
    // location format: "path:start-end"
    assert(/^.+:-?\d+-\d+$/.test(sym.location), `location should match path:start-end, got ${sym.location}`);
  }
  console.log(`find_symbol output format OK: ${result.symbols.length} symbols`);

  await client.shutdown();
}

// -- main ------------------------------------------------------------------

async function run(): Promise<void> {
  client = new SerenaBridgeClient(packageRoot);

  console.log("=== Init/Shutdown (Issue #1) ===");
  await testInitShutdown();

  console.log("\n=== find_symbol basic (Issue #3) ===");
  await testFindSymbolBasic();

  console.log("\n=== find_symbol with code_snippet (Issue #3) ===");
  await testFindSymbolWithSnippet();

  console.log("\n=== find_symbol output format (Issue #3) ===");
  await testFindSymbolOutputFormat();

  console.log(`\nPASS jsonl regression: ${fixtureRoot}`);
}

run().catch(async (error) => {
  console.error(`FAIL jsonl regression: ${error instanceof Error ? error.stack : error}`);
  if (client) {
    try { await client.shutdown(); } catch { /* ignore */ }
  }
  process.exitCode = 1;
});
