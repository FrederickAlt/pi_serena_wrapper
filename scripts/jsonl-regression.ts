#!/usr/bin/env node
/**
 * Regression test for the Serena bridge — Issues #1, #3, #4, #5.
 */

import { mkdir, rm, writeFile, readdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { SerenaBridgeClient, SerenaError } from "../src/bridge-client.js";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fixtureRoot = path.join(os.tmpdir(), `pi-serena-lsp-jsonl-${process.pid}`);

let client: SerenaBridgeClient;

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

type SymbolEntry = { name_path: string; kind: string; location: string };
type FindSymbolResult = SymbolEntry[];

function stripSentinel(symbols: FindSymbolResult): SymbolEntry[] {
  return symbols.filter(s => s.name_path !== "--truncated--");
}

function isTruncated(symbols: FindSymbolResult): boolean {
  return symbols.some(s => s.name_path === "--truncated--");
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
  await writeFile(path.join(fixtureRoot, "src", "lib", "utils.ts"), [
    "export class AnotherClass {",
    "  process(data: string): string {",
    "    return data.toUpperCase();",
    "  }",
    "",
    "  send(data: string): void {",
    "    console.log(data);",
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

async function writeTypeScriptFixtureWithInterface(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(path.join(fixtureRoot, "src"), { recursive: true });
  await writeFile(path.join(fixtureRoot, "package.json"), JSON.stringify({ type: "module" }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "tsconfig.json"), JSON.stringify({
    compilerOptions: { target: "ES2020", module: "ESNext", moduleResolution: "Node", strict: true },
    include: ["src/**/*.ts"],
  }, null, 2) + "\n");

  await writeFile(path.join(fixtureRoot, "src", "transport.ts"), `
export interface JsonRpcTransport {
  send(method: string, params: Record<string, unknown>): Promise<unknown>;
  isAlive(): boolean;
}

export class SubprocessTransport implements JsonRpcTransport {
  send(method: string, params: Record<string, unknown>): Promise<unknown> {
    return Promise.resolve(null);
  }
  isAlive(): boolean {
    return true;
  }
}

export function helper(): void {}
`);
  await writeFile(path.join(fixtureRoot, "src", "main.ts"), `
export function helper(x: number): number {
  return x * 2;
}
`);
}

async function writeTypeScriptFixtureWithImports(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(path.join(fixtureRoot, "src"), { recursive: true });
  await mkdir(path.join(fixtureRoot, "src", "lib"), { recursive: true });
  await writeFile(path.join(fixtureRoot, "package.json"), JSON.stringify({ type: "module" }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "tsconfig.json"), JSON.stringify({
    compilerOptions: { target: "ES2020", module: "ESNext", moduleResolution: "Node", strict: true },
    include: ["src/**/*.ts"],
  }, null, 2) + "\n");

  // Internal module: defines symbols that are imported elsewhere
  await writeFile(path.join(fixtureRoot, "src", "lib", "utils.ts"), [
    "export function validate(data: string): boolean {",
    "  return data.length > 0;",
    "}",
    "",
    "export function formatDate(date: Date): string {",
    "  return date.toISOString();",
    "}",
    "",
  ].join("\n") + "\n");

  // Main file with imports and local symbols
  await writeFile(path.join(fixtureRoot, "src", "index.ts"), [
    "import { validate, formatDate } from './lib/utils';",
    "import { useState, useEffect } from 'react';",
    "import something from 'some-lib';",
    "",
    "export class UserService {",
    "  createUser(name: string): void {",
    "    validate(name);",
    "  }",
    "",
    "  deleteUser(id: number): void {",
    "    console.log(`deleting ${id}`);",
    "  }",
    "}",
    "",
    "export function helper(): void {",
    "  console.log('helper');",
    "}",
    "",
  ].join("\n") + "\n");
}

async function writePythonFixtureWithImports(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(fixtureRoot, { recursive: true });
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - python\n",
  );

  // Internal module
  await writeFile(path.join(fixtureRoot, "utils.py"), [
    "def validate(data: str) -> bool:",
    "    return len(data) > 0",
    "",
    "def format_date(date_str: str) -> str:",
    "    return date_str.strip()",
    "",
  ].join("\n") + "\n");

  // Main file with imports and local symbols
  await writeFile(path.join(fixtureRoot, "main.py"), [
    "from utils import validate, format_date",
    "import os",
    "import sys",
    "",
    "class UserService:",
    "    def create_user(self, name: str) -> None:",
    "        validate(name)",
    "",
    "    def delete_user(self, uid: int) -> None:",
    "        print(f'deleting {uid}')",
    "",
    "def helper():",
    "    print('helper')",
    "",
  ].join("\n") + "\n");
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

  // --- get_document_overview on TypeScript fixture, depth=0 ---
  const tsOverviewDepth0 = await client.callTool("get_document_overview", { relative_path: "src/index.ts", depth: 0 }) as string;
  assert(typeof tsOverviewDepth0 === "string", `depth=0 should return a string, got ${typeof tsOverviewDepth0}`);
  assert(tsOverviewDepth0.includes("## Symbols"), "depth=0 should have Symbols section");
  const symbolsSection0 = tsOverviewDepth0.split("## Symbols")[1] || "";
  const lines0 = symbolsSection0.trim().split("\n").filter(l => l.trim());
  assert(lines0.length > 0, "depth=0 should return at least one symbol");
  for (const line of lines0) {
    assert(/^[A-Z][a-zA-Z]+ \w+:\d+-\d+$/.test(line), `depth=0 line should match "Kind Name:start-end": "${line}"`);
  }
  console.log(`get_document_overview depth=0 OK: ${lines0.length} top-level symbol(s)`);

  // --- get_document_overview on TypeScript fixture, depth=1 ---
  const tsOverviewDepth1 = await client.callTool("get_document_overview", { relative_path: "src/index.ts", depth: 1 }) as string;
  assert(typeof tsOverviewDepth1 === "string", `depth=1 should return a string, got ${typeof tsOverviewDepth1}`);
  const symbolsSection1 = tsOverviewDepth1.split("## Symbols")[1] || "";
  const lines1 = symbolsSection1.trim().split("\n").filter(l => l.trim());
  assert(lines1.length >= lines0.length, "depth=1 should include at least as many lines as depth=0");
  console.log(`get_document_overview depth=1 OK: ${lines1.length} lines`);

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

  // --- get_document_overview on Python fixture, depth=0 ---
  const pyOverviewDepth0 = await client.callTool("get_document_overview", { relative_path: "test.py", depth: 0 }) as string;
  assert(typeof pyOverviewDepth0 === "string", `Python depth=0 should return a string, got ${typeof pyOverviewDepth0}`);
  assert(pyOverviewDepth0.includes("## Symbols"), "Python depth=0 should have Symbols section");
  const pySymbolsSection = pyOverviewDepth0.split("## Symbols")[1] || "";
  const pyLines0 = pySymbolsSection.trim().split("\n").filter(l => l.trim());
  assert(pyLines0.length > 0, "Python depth=0 should return at least one symbol");
  console.log(`Python get_document_overview depth=0 OK: ${pyLines0.length} top-level symbol(s)`);

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

  // 1. find_symbol with just name_path
  const result1 = await client.callTool("find_symbol", { name_path: "MyClass" }) as FindSymbolResult;
  assert(Array.isArray(result1), "result should be an array");
  const syms1 = stripSentinel(result1);
  assert(syms1.length >= 1, `Expected at least 1 match for MyClass, got ${syms1.length}`);
  const mc = findSymbol(syms1, "MyClass");
  assert(mc !== undefined, "MyClass should be in results");
  assert(mc.kind === "Class", `MyClass kind should be Class, got ${mc.kind}`);
  console.log(`find_symbol name_path only OK: ${syms1.length} matches`);

  // 2. find_symbol for a method (nested name path)
  const result2 = await client.callTool("find_symbol", { name_path: "MyClass/greet" }) as FindSymbolResult;
  const syms2 = stripSentinel(result2);
  const greet = findSymbol(syms2, "MyClass/greet");
  assert(greet !== undefined, "MyClass/greet should be in results");
  assert(greet.kind === "Method", `MyClass/greet kind should be Method, got ${greet.kind}`);
  console.log(`find_symbol nested name_path OK: ${syms2.length} matches`);

  // 3. find_symbol with just last component (pattern match)
  const result2b = await client.callTool("find_symbol", { name_path: "send" }) as FindSymbolResult;
  const syms2b = stripSentinel(result2b);
  const sendMatch = syms2b.find((s) => s.name_path.endsWith("/send") || s.name_path === "send");
  assert(sendMatch !== undefined, "send should match MyClass/send via pattern");
  console.log(`find_symbol single-component pattern OK: ${syms2b.length} matches`);

  // 4. find_symbol with absolute (leading /) name path
  const result2c = await client.callTool("find_symbol", { name_path: "/MyClass/greet" }) as FindSymbolResult;
  const syms2c = stripSentinel(result2c);
  const exactMatch = findSymbol(syms2c, "MyClass/greet");
  assert(exactMatch !== undefined, "/MyClass/greet should exactly match MyClass/greet");
  console.log(`find_symbol absolute name_path OK: ${syms2c.length} matches`);

  // 5. find_symbol with relative_path scoped to src/lib
  const result3 = await client.callTool("find_symbol", {
    name_path: "AnotherClass",
    relative_path: "src/lib",
  }) as FindSymbolResult;
  const syms3 = stripSentinel(result3);
  assert(syms3.length >= 1, `Expected AnotherClass in src/lib, got ${syms3.length}`);
  const ac = findSymbol(syms3, "AnotherClass");
  assert(ac !== undefined, "AnotherClass should be in scoped results");
  console.log(`find_symbol with relative_path OK: ${syms3.length} matches`);

  // 6. find_symbol with kinds filter
  const result4 = await client.callTool("find_symbol", {
    name_path: "MyClass",
    kinds: [5],  // Class = 5
  }) as FindSymbolResult;
  const syms4 = stripSentinel(result4);
  assert(syms4.length >= 1, "kinds filter [5] should include MyClass");
  for (const s of syms4) {
    assert(s.kind === "Class", `All results should be Class, got ${s.kind}`);
  }
  console.log(`find_symbol kinds filter OK: ${syms4.length} matches`);

  // 7. find_symbol with max_matches and truncated — search for "send" which
  //    matches MyClass/send + any other send in the fixture, cap at 1.
  const result5 = await client.callTool("find_symbol", {
    name_path: "send",
    max_matches: 1,
  }) as FindSymbolResult;
  assert(isTruncated(result5), "max_matches=1 on multi-match pattern should produce sentinel");
  const syms5 = stripSentinel(result5);
  assert(syms5.length === 1, `max_matches=1 should cap to 1 symbol, got ${syms5.length}`);
  // Verify sentinel is the last entry
  const last5 = result5[result5.length - 1];
  assert(last5.name_path === "--truncated--", "sentinel should have name_path '--truncated--'");
  assert(last5.kind === "None" && last5.location === "None", "sentinel kind/location should be 'None'");
  console.log(`find_symbol max_matches OK: ${syms5.length} matches, truncated=${isTruncated(result5)}`);

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

  // code_snippet (project-wide)
  const result6 = await client.callTool("find_symbol", {
    name_path: "MyClass/send",
    code_snippet: "console.log",
  }) as FindSymbolResult;
  assert(Array.isArray(result6), "result should be an array");
  console.log(`find_symbol with code_snippet project-wide OK: ${stripSentinel(result6).length} matches`);

  // code_snippet + relative_path
  const result7 = await client.callTool("find_symbol", {
    name_path: "MyClass/send",
    code_snippet: "console.log",
    relative_path: "src",
  }) as FindSymbolResult;
  assert(Array.isArray(result7), "result should be an array");
  console.log(`find_symbol with code_snippet + relative_path OK: ${stripSentinel(result7).length} matches`);

  // code_snippet + kinds
  const result8 = await client.callTool("find_symbol", {
    name_path: "MyClass/send",
    code_snippet: "console.log",
    kinds: [6],  // Method = 6
  }) as FindSymbolResult;
  assert(Array.isArray(result8), "result should be an array");
  const syms8 = stripSentinel(result8);
  for (const s of syms8) {
    assert(s.kind === "Method", `All results should be Method, got ${s.kind}`);
  }
  console.log(`find_symbol with code_snippet + kinds OK: ${syms8.length} matches`);

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
  assert(Array.isArray(result), "result should be an array");
  assert(!isTruncated(result), "should not be truncated for 1-class fixture");
  const syms = stripSentinel(result);
  for (const sym of syms) {
    assert(typeof sym.name_path === "string", "name_path should be string");
    assert(typeof sym.kind === "string", "kind should be string");
    assert(typeof sym.location === "string", "location should be string");
    assert(/^.+:\d+-\d+$/.test(sym.location), `location should match path:start-end, got ${sym.location}`);
  }
  // Verify sentinel format when it does appear (tested separately in max_matches)
  console.log(`find_symbol output format OK: ${syms.length} symbols`);

  await client.shutdown();
}

async function testGetType(): Promise<void> {
  await writeTypeScriptFixtureWithInterface();
  const initResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(initResult.ok === true, `Init should succeed: ${JSON.stringify(initResult)}`);
  console.log(`Init OK: language=${initResult.language}`);

  // Give LSP a moment to index
  await new Promise(r => setTimeout(r, 5000));

  // --- exact name_path returns compact symbol info ---
  const typeResult = await client.callTool("get_type", {
    name_path: "JsonRpcTransport",
  }) as Record<string, unknown>;
  console.log("get_type(JsonRpcTransport):", JSON.stringify(typeResult));
  assert(typeof typeResult.name_path === "string", "Result should have name_path");
  assert(typeof typeResult.kind === "string", "Result should have kind");
  assert(typeof typeResult.location === "string", "Result should have location");
  assert(typeResult.kind === "Interface", `Expected kind=Interface, got ${typeResult.kind}`);
  console.log("  => exact match OK");

  // --- ambiguous name_path returns error with candidates ---
  try {
    await client.callTool("get_type", { name_path: "helper" });
    assert(false, "Ambiguous name_path should have thrown");
  } catch (err) {
    if (err instanceof SerenaError && err.errorKind === "ambiguity") {
      console.log(`Ambiguity OK: ${err.message}`);
      assert(Array.isArray(err.errorData.candidates), "Should have candidates array");
      assert((err.errorData.candidates as unknown[]).length > 1, "Should have multiple candidates");
      console.log("  => ambiguity OK");
    } else {
      throw err;
    }
  }

  // --- zero-match name_path returns error ---
  try {
    await client.callTool("get_type", { name_path: "nonexistent_symbol_xyzzy" });
    assert(false, "Zero-match name_path should have thrown");
  } catch (err) {
    if (err instanceof SerenaError) {
      console.log(`Zero-match OK: ${err.message}`);
      assert(err.message.includes("No symbol matches"), `Expected 'No symbol matches' error, got: ${err.message}`);
      console.log("  => zero-match OK");
    } else {
      throw err;
    }
  }

  // --- removed tools are rejected ---
  const removedTools = ["get_symbol_from_snippet", "find_declaration"];
  for (const toolName of removedTools) {
    try {
      await client.callTool(toolName, {});
      assert(false, `Removed tool ${toolName} should be rejected`);
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err);
      console.log(`Removed tool ${toolName} rejected: ${errMsg}`);
      assert(
        errMsg.includes("Unknown tool"),
        `Expected Unknown tool error for ${toolName}, got: ${errMsg}`,
      );
      console.log(`  => ${toolName} rejected OK`);
    }
  }

  await client.shutdown();
}

async function testGetDocumentOverview(): Promise<void> {
  // --- TypeScript fixture ---
  await writeTypeScriptFixtureWithImports();
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - typescript\n",
  );
  let initResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(initResult.ok === true, `Init should succeed: ${JSON.stringify(initResult)}`);
  console.log(`TypeScript init OK: language=${initResult.language}`);

  // Give LSP a moment to index
  await new Promise(r => setTimeout(r, 3000));

  // --- Call get_document_overview on the main file ---
  const tsOverview = await client.callTool("get_document_overview", {
    relative_path: "src/index.ts",
    depth: 0,
  }) as string;

  assert(typeof tsOverview === "string", `Expected string, got ${typeof tsOverview}`);
  console.log("TypeScript get_document_overview output:\n" + tsOverview);

  // Should have both sections
  assert(tsOverview.includes("## Imports"), "Should have Imports section");
  assert(tsOverview.includes("## Symbols"), "Should have Symbols section");

  // Imports section: check module grouping
  assert(tsOverview.includes("./lib/utils"), "Should include internal module path");
  assert(/\[internal/.test(tsOverview), "Should have [internal] classification");
  assert(/\[external\]/.test(tsOverview), "Should have [external] classification");

  // Symbols section: check format and local-only
  const symbolsSection = tsOverview.split("## Symbols")[1] || "";
  const symbolLines = symbolsSection.trim().split("\n").filter(l => l.trim());
  assert(symbolLines.length >= 1, "Should have at least one symbol");

  // Each symbol line: Kind Name:start-end (no leading indent at depth=0)
  for (const line of symbolLines) {
    // Allow optional indent + Kind + space + Name + : + digits + - + digits
    assert(/^\s*[A-Z][a-zA-Z]+ \w+:\d+-\d+$/.test(line),
      `Symbol line should match "Kind Name:start-end": "${line}"`);
  }

  // Imported names should NOT appear in Symbols section
  assert(!symbolsSection.includes("validate"), "validate is imported, should not be in Symbols");
  assert(!symbolsSection.includes("formatDate"), "formatDate is imported, should not be in Symbols");
  assert(!symbolsSection.includes("useState"), "useState is imported, should not be in Symbols");

  // Local symbols should appear
  assert(symbolsSection.includes("UserService"), "UserService should be in Symbols");
  assert(symbolsSection.includes("helper"), "helper should be in Symbols");

  console.log("  => TypeScript overview format OK");

  // --- Test depth=1 ---
  const tsOverviewDepth1 = await client.callTool("get_document_overview", {
    relative_path: "src/index.ts",
    depth: 1,
  }) as string;
  const symSectionDepth1 = tsOverviewDepth1.split("## Symbols")[1] || "";
  assert(symSectionDepth1.includes("createUser"), "depth=1 should include class members");
  assert(symSectionDepth1.includes("deleteUser"), "depth=1 should include class members");
  // Class members should be indented
  assert(
    symSectionDepth1.split("\n").some(l => l.includes("createUser") && l.startsWith("  ")),
    "depth=1 class members should have 2-space indent",
  );
  console.log("  => TypeScript depth=1 OK");

  await client.shutdown();

  // --- Python fixture ---
  await writePythonFixtureWithImports();
  initResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(initResult.ok === true, `Python init should succeed: ${JSON.stringify(initResult)}`);
  console.log(`Python init OK: language=${initResult.language}`);

  await new Promise(r => setTimeout(r, 3000));

  const pyOverview = await client.callTool("get_document_overview", {
    relative_path: "main.py",
    depth: 0,
  }) as string;

  assert(typeof pyOverview === "string", `Expected string, got ${typeof pyOverview}`);
  console.log("Python get_document_overview output:\n" + pyOverview);

  assert(pyOverview.includes("## Imports"), "Python should have Imports section");
  assert(pyOverview.includes("## Symbols"), "Python should have Symbols section");
  assert(pyOverview.includes("utils"), "Should include internal module 'utils'");
  assert(/\[internal/.test(pyOverview), "Should have [internal] classification");
  assert(/\[external\]/.test(pyOverview), "Should have [external] classification");

  const pySymbolsSection = pyOverview.split("## Symbols")[1] || "";
  const pySymbolLines = pySymbolsSection.trim().split("\n").filter(l => l.trim());
  assert(pySymbolLines.length >= 1, "Python should have at least one symbol");

  for (const line of pySymbolLines) {
    assert(/^\s*[A-Z][a-zA-Z]+ \w+:\d+-\d+$/.test(line),
      `Python symbol line should match format: "${line}"`);
  }

  // Imported names should NOT appear in Symbols section
  assert(!pySymbolsSection.includes("validate"), "validate is imported, should not be in Symbols");
  assert(!pySymbolsSection.includes("format_date"), "format_date is imported, should not be in Symbols");

  // Local symbols should appear
  assert(pySymbolsSection.includes("UserService"), "UserService should be in Symbols");
  assert(pySymbolsSection.includes("helper"), "helper should be in Symbols");

  console.log("  => Python overview format OK");

  await client.shutdown();
}

// -- aliased import fixtures (Issue #16) ------------------------------------

async function writeTypeScriptFixtureWithAliasedImports(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(path.join(fixtureRoot, "src"), { recursive: true });
  await mkdir(path.join(fixtureRoot, "src", "lib"), { recursive: true });
  await writeFile(path.join(fixtureRoot, "package.json"), JSON.stringify({ type: "module" }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "tsconfig.json"), JSON.stringify({
    compilerOptions: { target: "ES2020", module: "ESNext", moduleResolution: "Node", strict: true },
    include: ["src/**/*.ts"],
  }, null, 2) + "\n");

  // Internal module: defines symbols that are imported with aliases
  await writeFile(path.join(fixtureRoot, "src", "lib", "utils.ts"), [
    "export function validate(data: string): boolean {",
    "  return data.length > 0;",
    "}",
    "",
    "export function formatDate(date: Date): string {",
    "  return date.toISOString();",
    "}",
    "",
  ].join("\n") + "\n");

  // Main file with aliased imports and local symbols
  await writeFile(path.join(fixtureRoot, "src", "index.ts"), [
    "import { validate as val, formatDate } from './lib/utils';",
    "import { useState } from 'react';",
    "import defaultExport from 'some-lib';",
    "",
    "export class UserService {",
    "  check(data: string): boolean {",
    "    return val(data);",
    "  }",
    "",
    "  process(date: Date): string {",
    "    return formatDate(date);",
    "  }",
    "}",
    "",
    "export function helper(): void {",
    "  console.log('helper');",
    "}",
    "",
  ].join("\n") + "\n");
}

async function writePythonFixtureWithAliasedImports(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(fixtureRoot, { recursive: true });
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - python\n",
  );

  // Internal module
  await writeFile(path.join(fixtureRoot, "utils.py"), [
    "def validate(data: str) -> bool:",
    "    return len(data) > 0",
    "",
    "def format_date(date_str: str) -> str:",
    "    return date_str.strip()",
    "",
  ].join("\n") + "\n");

  // Main file with aliased imports and local symbols
  await writeFile(path.join(fixtureRoot, "main.py"), [
    "from utils import validate as val, format_date",
    "import os",
    "",
    "class UserService:",
    "    def check(self, data: str) -> bool:",
    "        return val(data)",
    "",
    "    def process(self, date_str: str) -> str:",
    "        return format_date(date_str)",
    "",
    "def helper():",
    "    print('helper')",
    "",
  ].join("\n") + "\n");
}

async function testGetDocumentOverviewCrossDir(): Promise<void> {
  // --- TypeScript cross-directory fixture ---
  await writeTypeScriptCrossDirFixture();
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - typescript\n",
  );
  let initResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(initResult.ok === true, `TS cross-dir init should succeed: ${JSON.stringify(initResult)}`);

  await new Promise(r => setTimeout(r, 3000));

  const tsOverview = await client.callTool("get_document_overview", {
    relative_path: "scripts/test.ts",
    depth: 0,
  }) as string;

  console.log("TS cross-dir import overview:\n" + tsOverview);

  // Imports section should show internal resolution with location
  assert(tsOverview.includes("## Imports"), "Should have Imports section");
  // The import from '../src/bridge-client.js' should resolve to src/bridge-client.ts
  assert(/\[internal → .*bridge-client\.ts:\d+-\d+\]/.test(tsOverview),
    "Cross-dir internal import should resolve to bridge-client.ts with line range");
  // Should NOT show bare [internal] for the resolved import
  assert(!/bridge-client.*\[internal\]\s*$/.test(tsOverview),
    "Cross-dir import should not fall back to bare [internal]");

  console.log("  => TS cross-dir import resolution OK");

  await client.shutdown();

  // --- Python cross-directory fixture ---
  await writePythonCrossDirFixture();
  initResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(initResult.ok === true, `Python cross-dir init should succeed: ${JSON.stringify(initResult)}`);

  await new Promise(r => setTimeout(r, 3000));

  const pyOverview = await client.callTool("get_document_overview", {
    relative_path: "scripts/test.py",
    depth: 0,
  }) as string;

  console.log("Python cross-dir import overview:\n" + pyOverview);

  // Imports section should show internal resolution with location
  assert(pyOverview.includes("## Imports"), "Python should have Imports section");
  // The relative import from '..src.utils' should resolve to src/utils.py
  assert(/\[internal → .*utils\.py:\d+-\d+\]/.test(pyOverview),
    "Python cross-dir internal import should resolve to utils.py with line range");
  assert(!/utils.*\[internal\]\s*$/.test(pyOverview),
    "Python cross-dir import should not fall back to bare [internal]");

  console.log("  => Python cross-dir import resolution OK");

  await client.shutdown();
}

async function testGetDocumentOverviewWithAliases(): Promise<void> {
  // --- TypeScript aliased fixture ---
  await writeTypeScriptFixtureWithAliasedImports();
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - typescript\n",
  );
  let initResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(initResult.ok === true, `TS alias init should succeed: ${JSON.stringify(initResult)}`);

  await new Promise(r => setTimeout(r, 3000));

  const tsOverview = await client.callTool("get_document_overview", {
    relative_path: "src/index.ts",
    depth: 0,
  }) as string;

  console.log("TS aliased import overview:\n" + tsOverview);

  // Alias display: validate (as val)
  assert(tsOverview.includes("validate (as val)"), "Should show 'validate (as val)'");
  // Non-aliased name in same module: formatDate shown normally
  assert(tsOverview.includes("formatDate"), "Should include formatDate");

  // Internal resolution: should resolve validate to utils.ts
  assert(/\[internal → .*utils\.ts:\d+-\d+\]/.test(tsOverview),
    "Aliased internal import should resolve to utils.ts");

  // Symbols section: 'val' should NOT appear (it's the alias/binding)
  const tsSymbolsSection = tsOverview.split("## Symbols")[1] || "";
  assert(!tsSymbolsSection.includes("val"), "Alias 'val' should not be in Symbols");
  assert(!tsSymbolsSection.includes("validate"), "Original 'validate' should not be in Symbols");
  assert(!tsSymbolsSection.includes("formatDate"), "Imported 'formatDate' should not be in Symbols");
  assert(!tsSymbolsSection.includes("useState"), "Imported 'useState' should not be in Symbols");
  assert(!tsSymbolsSection.includes("defaultExport"), "Imported 'defaultExport' should not be in Symbols");

  // Local symbols still present
  assert(tsSymbolsSection.includes("UserService"), "UserService should be in Symbols");
  assert(tsSymbolsSection.includes("helper"), "helper should be in Symbols");

  console.log("  => TS aliased import resolution OK");

  await client.shutdown();

  // --- Python aliased fixture ---
  await writePythonFixtureWithAliasedImports();
  initResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(initResult.ok === true, `Python alias init should succeed: ${JSON.stringify(initResult)}`);

  await new Promise(r => setTimeout(r, 3000));

  const pyOverview = await client.callTool("get_document_overview", {
    relative_path: "main.py",
    depth: 0,
  }) as string;

  console.log("Python aliased import overview:\n" + pyOverview);

  // Alias display: validate (as val)
  assert(pyOverview.includes("validate (as val)"), "Should show 'validate (as val)'");
  // Non-aliased name: format_date shown normally
  assert(pyOverview.includes("format_date"), "Should include format_date");

  // Internal resolution: should resolve validate to utils.py
  assert(/\[internal → .*utils\.py:\d+-\d+\]/.test(pyOverview),
    "Aliased internal import should resolve to utils.py");

  // Symbols section: 'val' should NOT appear
  const pySymbolsSection = pyOverview.split("## Symbols")[1] || "";
  assert(!pySymbolsSection.includes("val"), "Alias 'val' should not be in Symbols");
  assert(!pySymbolsSection.includes("validate"), "Original 'validate' should not be in Symbols");
  assert(!pySymbolsSection.includes("format_date"), "Imported 'format_date' should not be in Symbols");
  assert(!pySymbolsSection.includes("os"), "Imported 'os' should not be in Symbols");

  // Local symbols still present
  assert(pySymbolsSection.includes("UserService"), "UserService should be in Symbols");
  assert(pySymbolsSection.includes("helper"), "helper should be in Symbols");

  console.log("  => Python aliased import resolution OK");

  await client.shutdown();
}

// -- mixed-language fixtures (Issue #17) -----------------------------------

async function writeMixedLanguageFixture(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(fixtureRoot, { recursive: true });
  await mkdir(path.join(fixtureRoot, "src"), { recursive: true });
  await writeFile(path.join(fixtureRoot, "package.json"), JSON.stringify({ type: "module" }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "tsconfig.json"), JSON.stringify({
    compilerOptions: { target: "ES2020", module: "ESNext", moduleResolution: "Node", strict: true },
    include: ["src/**/*.ts"],
  }, null, 2) + "\n");

  // .serenaproject.yml with BOTH languages
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - typescript\n  - python\n",
  );

  // TypeScript file with imports and local symbols
  await writeFile(path.join(fixtureRoot, "src", "lib_utils.ts"), [
    "export function validate(data: string): boolean {",
    "  return data.length > 0;",
    "}",
    "",
  ].join("\n") + "\n");

  await writeFile(path.join(fixtureRoot, "src", "index.ts"), [
    "import { validate } from './lib_utils';",
    "import { useState } from 'react';",
    "",
    "export class MyService {",
    "  handle(data: string): boolean {",
    "    return validate(data);",
    "  }",
    "}",
    "",
    "export function helper(): void {",
    "  console.log('helper');",
    "}",
    "",
  ].join("\n") + "\n");

  // Python file with imports and local symbols
  await writeFile(path.join(fixtureRoot, "py_utils.py"), [
    "def validate(data: str) -> bool:",
    "    return len(data) > 0",
    "",
  ].join("\n") + "\n");

  await writeFile(path.join(fixtureRoot, "main.py"), [
    "from py_utils import validate",
    "import os",
    "",
    "class UserService:",
    "    def create_user(self, name: str) -> None:",
    "        validate(name)",
    "",
    "def helper():",
    "    print('helper')",
    "",
  ].join("\n") + "\n");
}

// -- cross-directory import fixtures (Issue #19) ----------------------------

async function writeTypeScriptCrossDirFixture(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(path.join(fixtureRoot, "src"), { recursive: true });
  await mkdir(path.join(fixtureRoot, "scripts"), { recursive: true });
  await writeFile(path.join(fixtureRoot, "package.json"), JSON.stringify({ type: "module" }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "tsconfig.json"), JSON.stringify({
    compilerOptions: { target: "ES2020", module: "ESNext", moduleResolution: "Node", strict: true },
    include: ["src/**/*.ts", "scripts/**/*.ts"],
  }, null, 2) + "\n");

  // Source file that defines the exported symbol
  await writeFile(path.join(fixtureRoot, "src", "bridge-client.ts"), [
    "export function SerenaBridgeClient(): string {",
    "  return 'bridge-client';",
    "}",
    "",
  ].join("\n") + "\n");

  // File in a subdirectory that imports from a parent directory
  await writeFile(path.join(fixtureRoot, "scripts", "test.ts"), [
    "import { SerenaBridgeClient } from '../src/bridge-client.js';",
    "",
    "const result = SerenaBridgeClient();",
    "",
  ].join("\n") + "\n");
}

async function writePythonCrossDirFixture(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(path.join(fixtureRoot, "src"), { recursive: true });
  await mkdir(path.join(fixtureRoot, "scripts"), { recursive: true });
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - python\n",
  );

  // Source file that defines the exported symbol
  await writeFile(path.join(fixtureRoot, "src", "utils.py"), [
    "def validate(data: str) -> bool:",
    "    return len(data) > 0",
    "",
  ].join("\n") + "\n");

  // File in a subdirectory that imports from a parent directory
  await writeFile(path.join(fixtureRoot, "scripts", "test.py"), [
    "from ..src.utils import validate",
    "",
    "def check(data: str) -> bool:",
    "    return validate(data)",
    "",
  ].join("\n") + "\n");
}

async function testMixedLanguageOverview(): Promise<void> {
  await writeMixedLanguageFixture();

  const initResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(initResult.ok === true, `Mixed init should succeed: ${JSON.stringify(initResult)}`);
  assert(Array.isArray(initResult.languages), `Should return languages array: ${JSON.stringify(initResult)}`);
  assert((initResult.languages as string[]).includes("typescript"), "Should include typescript");
  assert((initResult.languages as string[]).includes("python"), "Should include python");
  console.log(`Mixed init OK: languages=${JSON.stringify(initResult.languages)}`);

  await new Promise(r => setTimeout(r, 5000));

  // --- get_document_overview on TypeScript file ---
  const tsOverview = await client.callTool("get_document_overview", {
    relative_path: "src/index.ts",
    depth: 1,
  }) as string;

  console.log("TS overview in mixed project:\n" + tsOverview);

  // TypeScript file should have proper imports and symbols (not Python f-string fragments)
  assert(tsOverview.includes("## Imports"), "TS file should have Imports section");
  assert(tsOverview.includes("## Symbols"), "TS file should have Symbols section");
  assert(tsOverview.includes("./lib_utils"), "Should show internal TS module");
  assert(tsOverview.includes("[internal"), "Should have [internal] classification");
  assert(tsOverview.includes("MyService"), "MyService should be in Symbols");
  assert(tsOverview.includes("helper"), "helper should be in Symbols");
  assert(tsOverview.includes("handle"), "depth=1 should include class member 'handle'");

  // Must NOT contain Python f-string artifacts or wrong-language symbols
  assert(!tsOverview.includes("f-string"), "TS overview should not contain f-string fragments");

  console.log("  => TS overview in mixed project OK");

  // --- get_document_overview on Python file ---
  const pyOverview = await client.callTool("get_document_overview", {
    relative_path: "main.py",
    depth: 1,
  }) as string;

  console.log("Python overview in mixed project:\n" + pyOverview);

  // Python file should have proper imports and symbols (real Python classes/functions)
  assert(pyOverview.includes("## Imports"), "Python file should have Imports section");
  assert(pyOverview.includes("## Symbols"), "Python file should have Symbols section");
  assert(pyOverview.includes("py_utils"), "Should show internal Python module");
  assert(/\[internal/.test(pyOverview), "Should have [internal] classification");
  assert(pyOverview.includes("UserService"), "UserService should be in Symbols");
  assert(pyOverview.includes("helper"), "helper should be in Symbols");
  assert(pyOverview.includes("create_user"), "depth=1 should include class method 'create_user'");

  // Python symbols should be proper LSP kinds (Class, Function), not f-string fragments
  assert(/Class UserService:\d+-\d+/.test(pyOverview), "UserService should be Class kind");
  assert(/Function helper:\d+-\d+/.test(pyOverview), "helper should be Function kind");

  console.log("  => Python overview in mixed project OK");

  await client.shutdown();

  // --- Auto-detect and write .serenaproject.yml on first init ---
  await writeTypeScriptFixture(); // creates tsconfig.json + src/index.ts
  // Remove any existing .serenaproject.yml to test auto-write
  try {
    await rm(path.join(fixtureRoot, ".serenaproject.yml"), { force: true });
  } catch { /* ok */ }

  const autoInitResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(autoInitResult.ok === true, `Auto-detect init should succeed: ${JSON.stringify(autoInitResult)}`);

  // Check that .serenaproject.yml was created
  assert(existsSync(path.join(fixtureRoot, ".serenaproject.yml")), "should auto-write .serenaproject.yml");

  console.log(`Auto-detect init OK: wrote .serenaproject.yml`);

  await client.shutdown();
}

// -- lazy language server start (Issue #18) ----------------------------------

async function testLazyLanguageStart(): Promise<void> {
  // Reuse the mixed-language fixture (TS + Python files on disk)
  await writeMixedLanguageFixture();

  // Override .serenaproject.yml to list ONLY typescript
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - typescript\n",
  );

  // Init: only typescript should start
  const initResult1 = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(initResult1.ok === true, `Init (TS only) should succeed: ${JSON.stringify(initResult1)}`);
  assert(initResult1.language === "typescript", `Primary should be typescript: ${initResult1.language}`);
  const langs1 = initResult1.languages as string[];
  assert(langs1.length === 1, `Expected 1 language, got ${langs1.length}: ${JSON.stringify(langs1)}`);
  assert(langs1[0] === "typescript", `Should be typescript only: ${JSON.stringify(langs1)}`);
  console.log(`Init (TS only) OK: languages=${JSON.stringify(langs1)}`);

  await new Promise(r => setTimeout(r, 5000));

  // Call get_document_overview on a .py file → should lazily start Python
  const pyOverview = await client.callTool("get_document_overview", {
    relative_path: "main.py",
    depth: 0,
  }) as string;

  console.log("Lazy-start Python overview:\n" + pyOverview);

  // Must NOT be TypeScript artifacts on the Python file
  assert(!pyOverview.includes("f-string"), "Python file should not have TS f-string artifacts");
  assert(pyOverview.includes("## Imports"), "Python file should have Imports section");
  assert(pyOverview.includes("## Symbols"), "Python file should have Symbols section");
  // Python-specific symbols should be proper LSP kinds
  assert(/Class UserService:\d+-\d+/.test(pyOverview), "UserService should be a Class");
  assert(/Function helper:\d+-\d+/.test(pyOverview), "helper should be a Function");
  // Imported names should be excluded from Symbols
  const pySymbolsSection = pyOverview.split("## Symbols")[1] || "";
  assert(!pySymbolsSection.includes("validate"), "validate should not be in Symbols");
  console.log("  => Python overview via lazy start OK");

  // Check that .serenaproject.yml was NOT mutated (lazy start is in-memory only)
  const { readFileSync } = await import("node:fs");
  const configAfter = readFileSync(path.join(fixtureRoot, ".serenaproject.yml"), "utf-8");
  assert(!configAfter.includes("python"), `.serenaproject.yml should NOT include python (lazy start is read-only):\n${configAfter}`);
  assert(configAfter.includes("typescript"), `.serenaproject.yml should still include typescript:\n${configAfter}`);
  console.log("  => .serenaproject.yml unchanged OK (lazy start is in-memory)");

  // Call get_document_overview on the Python file (also uses _ls_for_file)
  const pyOverview2 = await client.callTool("get_document_overview", {
    relative_path: "main.py",
    depth: 0,
  }) as string;
  assert(typeof pyOverview2 === "string", "Python get_document_overview should return string");
  assert(pyOverview2.includes("UserService"), "Python overview should include UserService");
  console.log("  => Python get_document_overview via lazy start OK");

  await client.shutdown();

  // Re-init: only the originally-configured languages (lazy start is in-memory)
  const initResult2 = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(initResult2.ok === true, `Re-init should succeed: ${JSON.stringify(initResult2)}`);
  const langs2 = initResult2.languages as string[];
  assert(langs2.length === 1, `Expected exactly 1 language on re-init (lazy start is in-memory), got ${langs2.length}: ${JSON.stringify(langs2)}`);
  assert(langs2.includes("typescript"), `Should include typescript: ${JSON.stringify(langs2)}`);
  console.log(`Re-init OK: languages=${JSON.stringify(langs2)}`);

  await client.shutdown();
}

// -- name collision fixture (Issue #24) ------------------------------------

async function writePythonFixtureWithNameCollision(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(fixtureRoot, { recursive: true });
  await writeFile(
    path.join(fixtureRoot, ".serenaproject.yml"),
    "languages:\n  - python\n",
  );

  // Internal library with a class named 'Language' — exactly the name
  // that tree_sitter exports externally.  This creates a name collision.
  await writeFile(path.join(fixtureRoot, "internal_lib.py"), [
    "class Language:",
    "    pass",
    "",
  ].join("\n") + "\n");

  // Main file imports 'Language' from the fictional external 'tree_sitter'
  // AND from the internal 'internal_lib' module.
  await writeFile(path.join(fixtureRoot, "main.py"), [
    "from tree_sitter import Language, Parser",  // external — must stay [external]
    "from internal_lib import Language as LibLanguage",  // internal — must be [internal]
    "import os",
    "",
    "def helper():",
    "    pass",
    "",
  ].join("\n") + "\n");
}

async function testImportClassificationNameCollision(): Promise<void> {
  await writePythonFixtureWithNameCollision();

  const initResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(initResult.ok === true, `Init should succeed: ${JSON.stringify(initResult)}`);
  console.log(`Name collision init OK: language=${initResult.language}`);

  await new Promise(r => setTimeout(r, 4000));

  const overview = await client.callTool("get_document_overview", {
    relative_path: "main.py",
    depth: 0,
  }) as string;

  console.log("Name collision overview:\n" + overview);

  // tree_sitter is an external package — must NOT be classified as internal
  // even though `Language` also exists as an internal class in internal_lib.py
  assert(overview.includes("## Imports"), "Should have Imports section");
  assert(/tree_sitter.*\[external\]/.test(overview),
    "tree_sitter should be [external] even with internal Language class");
  assert(!/tree_sitter.*\[internal/.test(overview),
    "tree_sitter must NOT be classified as [internal]");

  // internal_lib is local — must be classified as internal
  assert(/internal_lib.*\[internal/.test(overview),
    "internal_lib should be [internal]");

  // os is standard library — must be external
  assert(/os.*\[external\]/.test(overview),
    "os should be [external]");

  console.log("  => import classification with name collision OK");

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

  console.log("\n=== get_type (Issue #5) ===");
  await testGetType();

  console.log("\n=== get_document_overview (Issue #14) ===");
  await testGetDocumentOverview();

  console.log("\n=== get_document_overview with aliases (Issue #16) ===");
  await testGetDocumentOverviewWithAliases();

  console.log("\n=== mixed-language dispatch (Issue #17) ===");
  await testMixedLanguageOverview();

  console.log("\n=== get_document_overview cross-dir import (Issue #19) ===");
  await testGetDocumentOverviewCrossDir();

  console.log("\n=== lazy language server start (Issue #18) ===");
  await testLazyLanguageStart();

  console.log("\n=== import classification name collision (Issue #24) ===");
  await testImportClassificationNameCollision();

  console.log(`\nPASS jsonl regression: ${fixtureRoot}`);
}

async function cleanupSandcastleWorktrees(): Promise<void> {
  const worktreesDir = path.join(packageRoot, ".sandcastle", "worktrees");
  if (!existsSync(worktreesDir)) return;
  try {
    const entries = await readdir(worktreesDir);
    for (const entry of entries) {
      if (entry.startsWith("pi-test-disposable-")) {
        const fullPath = path.join(worktreesDir, entry);
        await rm(fullPath, { recursive: true, force: true });
        console.log(`Cleaned up sandcastle worktree: ${fullPath}`);
      }
    }
  } catch { /* ignore */ }
}

run()
  .then(async () => {
    try {
      await rm(fixtureRoot, { recursive: true, force: true });
      console.log(`Cleaned up fixture: ${fixtureRoot}`);
    } catch { /* ignore */ }
    await cleanupSandcastleWorktrees();
  })
  .catch(async (error) => {
    console.error(`FAIL jsonl regression: ${error instanceof Error ? error.stack : error}`);
    if (client) {
      try { await client.shutdown(); } catch { /* ignore */ }
    }
    try {
      await rm(fixtureRoot, { recursive: true, force: true });
    } catch { /* ignore */ }
    await cleanupSandcastleWorktrees();
    process.exitCode = 1;
  });
