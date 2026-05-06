import { access, cp, mkdir, rm, writeFile } from "node:fs/promises";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const runRegression = args.includes("--test");
const sourceArg = args.find((arg) => arg !== "--test");
const sourceRoot = path.resolve(sourceArg ?? path.join(packageRoot, "..", "serena"));
const vendorRoot = path.join(packageRoot, "vendor", "serena");
const sourceDirs = ["serena", "solidlsp", "interprompt"];
const sourceFiles = ["pyproject.toml", "LICENSE", "README.md"];

async function requirePath(pathname: string) {
  try {
    await access(pathname);
  } catch {
    throw new Error(`Required path is missing: ${pathname}`);
  }
}

async function verifySourceTree() {
  for (const dir of sourceDirs) {
    await requirePath(path.join(sourceRoot, "src", dir));
  }
  for (const file of sourceFiles) {
    await requirePath(path.join(sourceRoot, file));
  }
}

async function copyRequiredTree() {
  await rm(vendorRoot, { recursive: true, force: true });
  await mkdir(path.join(vendorRoot, "src"), { recursive: true });

  for (const dir of sourceDirs) {
    await cp(path.join(sourceRoot, "src", dir), path.join(vendorRoot, "src", dir), { recursive: true });
  }

  for (const file of sourceFiles) {
    await cp(path.join(sourceRoot, file), path.join(vendorRoot, file));
  }
}

async function verifyVendorTree() {
  for (const dir of sourceDirs) {
    await requirePath(path.join(vendorRoot, "src", dir));
  }
  for (const file of [...sourceFiles, "UPSTREAM.json"]) {
    await requirePath(path.join(vendorRoot, file));
  }
}

function git(args: string[]): string | undefined {
  const result = spawnSync("git", args, { cwd: sourceRoot, encoding: "utf8" });
  return result.status === 0 ? result.stdout.trim() : undefined;
}

async function writeMetadata() {
  const metadata = {
    upstream: "https://github.com/oraios/serena",
    sourceRoot,
    ref: git(["rev-parse", "--abbrev-ref", "HEAD"]),
    sha: git(["rev-parse", "HEAD"]),
    updatedAt: new Date().toISOString(),
  };
  await writeFile(path.join(vendorRoot, "UPSTREAM.json"), `${JSON.stringify(metadata, null, 2)}\n`, "utf8");
}

function runJsonlRegression() {
  const result = spawnSync("node", ["scripts/jsonl-regression.mjs"], { cwd: packageRoot, encoding: "utf8", stdio: "inherit" });
  if (result.status !== 0) {
    throw new Error(`JSONL regression failed after vendor sync with exit status ${result.status}`);
  }
}

await verifySourceTree();
await copyRequiredTree();
await writeMetadata();
await verifyVendorTree();
if (runRegression) runJsonlRegression();
