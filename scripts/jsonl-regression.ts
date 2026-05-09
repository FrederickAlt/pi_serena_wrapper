#!/usr/bin/env node
/** Regression test for the Serena bridge via SerenaBridgeClient. */

import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { SerenaBridgeClient } from "../src/bridge-client.js";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fixtureRoot = path.join(os.tmpdir(), `pi-serena-lsp-jsonl-${process.pid}`);
const failedToolLog = path.join(packageRoot, ".serena-data", "failed-tool-calls.jsonl");
const expectedTools = [
  "get_symbols_overview",
  "find_symbol",
  "get_symbol_from_snippet",
  "find_referencing_symbols",
  "find_declaration",
  "find_implementations",
  "rename_symbol",
];
const removedTools = ["get_diagnostics_for_file", "get_diagnostics_for_symbol", "find_type_definition"];

let client: SerenaBridgeClient;

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function stringify(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

async function writeFixture(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(path.join(fixtureRoot, "src"), { recursive: true });
  await writeFile(path.join(fixtureRoot, "package.json"), JSON.stringify({ type: "module" }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "tsconfig.json"), JSON.stringify({
    compilerOptions: { target: "ES2020", module: "ESNext", moduleResolution: "Node", strict: true },
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

export default function (name: string): string {
  return makeGreeting(name);
}
`);
  await writeFile(path.join(fixtureRoot, "src", "usage.ts"), `import { Greeter, makeGreeting } from "./index";

export function useGreeting(): string {
  const greeter = new Greeter();
  const namedGreeter: Greeter = greeter;
  return greeter.greet("World") + makeGreeting("Serena");
}

export function useGreetingTwice(): string {
  const speaker = new Greeter();
  const first = speaker.greet("First");
  return first + speaker.greet("Second");
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
  await writeFile(path.join(fixtureRoot, "src", "ambiguous-rename.ts"), `export function first(signal: string): string {
  return signal.trim();
}

export function second(signal: string): string {
  return signal.toUpperCase();
}
`);
}

async function writePythonFixture(): Promise<void> {
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

async function writeMixedDemandFixture(): Promise<string> {
  const mixedRoot = path.join(fixtureRoot, "mixed-demand");
  await mkdir(path.join(mixedRoot, "src"), { recursive: true });
  await mkdir(path.join(mixedRoot, "tests"), { recursive: true });
  await writeFile(path.join(mixedRoot, "src", "index.ts"), `export function tsThing(): number {
  return 1;
}
`);
  await writeFile(path.join(mixedRoot, "tests", "test_sample.py"), `def py_thing():
    return 2
`);
  return mixedRoot;
}

async function expectUnknownTool(tool: string): Promise<void> {
  try {
    await client.callTool(fixtureRoot, tool, {});
    throw new Error(`${tool} unexpectedly succeeded`);
  } catch (error: unknown) {
    assert(error instanceof Error && error.message.includes("Unknown Serena pi tool"),
      `${tool} should be rejected as unknown`);
  }
}

async function run(): Promise<void> {
  await writeFixture();
  await writePythonFixture();
  await rm(failedToolLog, { force: true });

  client = new SerenaBridgeClient();

  // --- Verify tool listing ---
  const tools = await client.listTools(fixtureRoot);
  assert(JSON.stringify(tools) === JSON.stringify(expectedTools),
    `Unexpected tools: ${JSON.stringify(tools)}`);
  for (const removedTool of removedTools) {
    assert(!(tools as string[]).includes(removedTool),
      `${removedTool} should not be exposed`);
    await expectUnknownTool(removedTool);
  }

  // --- get_symbols_overview ---
  const overview = stringify(await client.callTool(fixtureRoot, "get_symbols_overview", {
    relative_path: "src/index.ts", depth: 1,
  }));
  assert(overview.includes("Greeter") && overview.includes("makeGreeting") && overview.includes("Runner"), overview);

  // --- find_symbol ---
  const symbol = stringify(await client.callTool(fixtureRoot, "find_symbol", {
    relative_path: "src/index.ts", name_path: "Greeter", depth: 1,
  }));
  assert(symbol.includes("Greeter") && symbol.includes("greet"), symbol);

  // --- get_symbol_from_snippet (usage) ---
  const symbolFromSnippet = JSON.parse(await client.callTool(fixtureRoot, "get_symbol_from_snippet", {
    relative_path: "src/usage.ts",
    code_snippet: '.greet("World")',
    symbol_text: "greet",
  }) as string);
  assert(
    (symbolFromSnippet.symbols as any[]).some((m: any) => m.name_path === "Greeter/greet"),
    JSON.stringify(symbolFromSnippet),
  );

  // --- find_referencing_symbols ---
  const references = stringify(await client.callTool(fixtureRoot, "find_referencing_symbols", {
    relative_path: "src/index.ts", name_path: "Greeter/greet",
  }));
  assert(references.includes("src/usage.ts") || references.includes("useGreeting"), references);

  // --- find_declaration ---
  const declaration = stringify(await client.callTool(fixtureRoot, "find_declaration", {
    relative_path: "src/index.ts", name_path: "Greeter/greet",
  }));
  assert(declaration.includes("src/index.ts") && declaration.includes("greet"), declaration);

  const ownDeclaration = stringify(await client.callTool(fixtureRoot, "find_declaration", {
    relative_path: "src/index.ts", name_path: "default",
  }));
  assert(ownDeclaration.includes("src/index.ts") && ownDeclaration.includes("default"), ownDeclaration);

  // --- import specifier snippet ---
  const importSpecifier = JSON.parse(await client.callTool(fixtureRoot, "get_symbol_from_snippet", {
    relative_path: "src/usage.ts",
    code_snippet: 'import { Greeter, makeGreeting } from "./index";',
    symbol_text: "Greeter",
  }) as string);
  assert(Array.isArray(importSpecifier.symbols), JSON.stringify(importSpecifier));
  if (importSpecifier.symbols.length === 0) {
    assert(
      importSpecifier.unresolved?.reason === "external_or_unindexed_target"
        || importSpecifier.unresolved?.reason === "no_lsp_target",
      JSON.stringify(importSpecifier),
    );
  }

  // --- type_definition via snippet ---
  const typeDefinition = stringify(await client.callTool(fixtureRoot, "get_symbol_from_snippet", {
    relative_path: "src/usage.ts",
    code_snippet: "namedGreeter: Greeter",
    symbol_text: "namedGreeter",
    resolve: "type_definition",
  }));
  assert(typeDefinition.includes("Greeter") && typeDefinition.includes("src/index.ts"), typeDefinition);

  // --- find_implementations ---
  const implementations = stringify(await client.callTool(fixtureRoot, "find_implementations", {
    relative_path: "src/index.ts", name_path: "Runner/run",
  }));
  assert(
    implementations.includes("ConcreteRunner") || implementations.includes("src/implementation.ts"),
    implementations,
  );

  // --- rename_symbol ---
  const rename = stringify(await client.callTool(fixtureRoot, "rename_symbol", {
    relative_path: "src/rename-target.ts", name_path: "renameMe", new_name: "renamedBySerena",
  }));
  const renamedTarget = await readFile(path.join(fixtureRoot, "src", "rename-target.ts"), "utf8");
  assert(rename.includes("renamedBySerena") || renamedTarget.includes("renamedBySerena"), rename);
  assert(renamedTarget.includes("renamedBySerena") && !renamedTarget.includes("renameMe"), renamedTarget);

  // --- ambiguous rename: resolve via snippet then rename ---
  const signalSymbol = JSON.parse(await client.callTool(fixtureRoot, "get_symbol_from_snippet", {
    relative_path: "src/ambiguous-rename.ts",
    code_snippet: "function first(signal: string)",
    symbol_text: "first",
  }) as string);
  assert(signalSymbol.symbols.length === 1, JSON.stringify(signalSymbol));

  // --- filtered snippet (line + column) ---
  const filteredSnippetSymbol = JSON.parse(await client.callTool(fixtureRoot, "get_symbol_from_snippet", {
    relative_path: "src/usage.ts",
    code_snippet: 'speaker.greet("',
    symbol_text: "greet",
    line: 11,
    column: 25,
  }) as string);
  assert(
    (filteredSnippetSymbol.symbols as any[]).some((m: any) => m.name_path === "Greeter/greet"),
    JSON.stringify(filteredSnippetSymbol),
  );

  // --- ambiguous rename execution ---
  const ambiguousRename = stringify(await client.callTool(fixtureRoot, "rename_symbol", {
    relative_path: signalSymbol.symbols[0].relative_path,
    name_path: signalSymbol.symbols[0].name_path,
    new_name: "firstSignal",
  }));
  const ambiguousRenamed = await readFile(path.join(fixtureRoot, "src", "ambiguous-rename.ts"), "utf8");
  assert(ambiguousRename.includes("firstSignal") || ambiguousRenamed.includes("firstSignal"), ambiguousRename);
  assert(ambiguousRenamed.includes("function firstSignal(signal: string)"), ambiguousRenamed);
  assert(ambiguousRenamed.includes("return signal.trim();"), ambiguousRenamed);
  assert(ambiguousRenamed.includes("second(signal: string)"), ambiguousRenamed);
  assert(ambiguousRenamed.includes("return signal.toUpperCase();"), ambiguousRenamed);

  // --- Shutdown + re-init for Python project ---
  await client.shutdown();

  // --- Python fixture (unsupported find_implementations) ---
  const unsupportedImplementations = stringify(await client.callTool(
    path.join(fixtureRoot, "py"),
    "find_implementations",
    { relative_path: "test.py", name_path: "MyInterface" },
  ));
  assert(
    unsupportedImplementations.includes("not supported by the active language server"),
    unsupportedImplementations,
  );
  assert(!unsupportedImplementations.includes("Traceback"), unsupportedImplementations);

  // --- Verify failed tool call log ---
  await client.shutdown();
  const finalFailureLog = await readFile(failedToolLog, "utf8");
  const finalFailureEntries = finalFailureLog.trim().split("\n").map((line) => JSON.parse(line));
  assert(
    finalFailureEntries.length === 1,
    `Expected one failed tool log entry, got ${finalFailureEntries.length}: ${finalFailureLog}`,
  );
  assert(finalFailureEntries[0].tool === "find_implementations", JSON.stringify(finalFailureEntries[0]));
  assert(finalFailureEntries[0].failure_kind === "error_result", JSON.stringify(finalFailureEntries[0]));

  // --- Mixed-demand fixture (multi-language) ---
  const mixedDemandRoot = await writeMixedDemandFixture();
  const demandTsOverview = stringify(await client.callTool(mixedDemandRoot, "get_symbols_overview", {
    relative_path: "src/index.ts", depth: 0,
  }));
  assert(demandTsOverview.includes("tsThing"), demandTsOverview);
  const demandPyOverview = stringify(await client.callTool(mixedDemandRoot, "get_symbols_overview", {
    relative_path: "tests/test_sample.py", depth: 0,
  }));
  assert(demandPyOverview.includes("py_thing"), demandPyOverview);

  await client.shutdown();
  console.log(`PASS jsonl regression fixture: ${fixtureRoot}`);
}

run().catch(async (error) => {
  console.error(`FAIL jsonl regression: ${error instanceof Error ? error.stack : error}`);
  if (client) {
    try { await client.shutdown(); } catch { /* ignore */ }
  }
  process.exitCode = 1;
});
