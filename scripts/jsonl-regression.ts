#!/usr/bin/env node
/** Regression test for the Serena bridge — Issue #5 (get_type + lifecycle). */

import { mkdir, rm, writeFile } from "node:fs/promises";
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

async function writeTypeScriptFixtureWithInterface(): Promise<void> {
  await rm(fixtureRoot, { recursive: true, force: true });
  await mkdir(path.join(fixtureRoot, "src"), { recursive: true });
  await writeFile(path.join(fixtureRoot, "package.json"), JSON.stringify({ type: "module" }, null, 2) + "\n");
  await writeFile(path.join(fixtureRoot, "tsconfig.json"), JSON.stringify({
    compilerOptions: { target: "ES2020", module: "ESNext", moduleResolution: "Node", strict: true },
    include: ["src/**/*.ts"],
  }, null, 2) + "\n");

  // File with an interface and a class implementing it
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
  // Second file with a top-level "helper" function — for ambiguity testing
  await writeFile(path.join(fixtureRoot, "src", "main.ts"), `
export function helper(x: number): number {
  return x * 2;
}
`);
}

async function run(): Promise<void> {
  client = new SerenaBridgeClient();

  // ========================================================================
  // Issue #5 — get_type tool tests
  // ========================================================================

  await writeTypeScriptFixtureWithInterface();
  const initResult = await client.init(fixtureRoot) as Record<string, unknown>;
  assert(initResult.ok === true, `Init should succeed: ${JSON.stringify(initResult)}`);
  console.log(`Init OK: language=${initResult.language}`);

  // Give the LSP a moment to index the project
  await new Promise(r => setTimeout(r, 5000));

  // --- 5a: get_type with exact name_path returns compact symbol info ---
  const typeResult = await client.callTool("get_type", {
    name_path: "JsonRpcTransport",
  }) as Record<string, unknown>;
  console.log("get_type(JsonRpcTransport):", JSON.stringify(typeResult));
  assert(typeof typeResult.name_path === "string", "Result should have name_path");
  assert(typeof typeResult.kind === "string", "Result should have kind");
  assert(typeof typeResult.location === "string", "Result should have location");
  assert(typeResult.kind === "Interface", `Expected kind=Interface, got ${typeResult.kind}`);
  console.log("  => exact match OK");

  // --- 5b: get_type with ambiguous name_path returns error with candidates ---
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

  // --- 5c: get_type with name_path matching zero symbols returns error ---
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

  // --- 5d: Removed tools are rejected ---
  const removedTools = ["get_symbol_from_snippet", "find_declaration"];
  for (const toolName of removedTools) {
    try {
      await client.callTool(toolName, {});
      assert(false, `Removed tool ${toolName} should be rejected`);
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err);
      console.log(`Removed tool ${toolName} rejected: ${errMsg}`);
      assert(
        errMsg.includes("Unknown tool") || errMsg.includes("Unknown method"),
        `Expected Unknown tool/method error for ${toolName}, got: ${errMsg}`,
      );
      console.log(`  => ${toolName} rejected OK`);
    }
  }

  await client.shutdown();

  console.log(`PASS jsonl regression (get_type): ${fixtureRoot}`);
}

run().catch(async (error) => {
  console.error(`FAIL jsonl regression: ${error instanceof Error ? error.stack : error}`);
  if (client) {
    try { await client.shutdown(); } catch { /* ignore */ }
  }
  process.exitCode = 1;
});
