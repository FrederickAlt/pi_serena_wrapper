# PRD: Improve `get_document_overview` Signal-to-Noise

## Problem Statement

`get_document_overview` is useful for fast orientation because it shows imports, local symbols, and line ranges. However, the current `## Symbols` output is still too shallow and too noisy for implementation planning:

- It omits source-faithful API details such as function signatures, class declarations, interface fields, enum members, and type shapes.
- It can include implementation noise from inside function/method bodies when filters are broadened, such as local constants, object-literal properties, and anonymous callback symbols.
- It is LSP-symbol-first, which is convenient but not ideal for local syntactic overview rendering: language servers vary in what they expose and often report symbols that are useful for IDE navigation but noisy for an agent overview.

As a result, agents still need to read full files in cases where a better overview could provide enough structural context.

## Solution

Improve `get_document_overview` so the `## Symbols` section becomes a fast, bounded, source-faithful structural summary of a file.

The central architectural decision is: **Tree-sitter-first for local overview rendering, LSP for semantic gaps and fallback.**

The improved overview should:

- Use project-owned Tree-sitter overview queries as the primary source for rendered symbols where a renderer exists.
- Keep language knowledge primarily in vendored `.scm` query files, not hardcoded Python node-type logic.
- Copy declaration/header text from source and strip/collapse implementation bodies.
- Show compact shape previews for structural declarations such as interfaces, type aliases, classes, and enums.
- Hide executable-body implementation detail by default.
- Preserve useful top-level API declarations, including exported/top-level constants and callable consts.
- Keep symbol-tree `depth` separate from shape-preview rendering.
- Fall back to the current LSP Symbols renderer when a Tree-sitter renderer is unavailable or structurally fails.
- Keep the current Imports section behavior: Tree-sitter parses imports; filesystem/module heuristics scope or verify candidates; LSP resolution provides internal import definition locations best-effort.

References/xrefs remain out of scope because dedicated LSP tools already exist for those tasks.

## Current Behavior Example

Current output can be underspecified and noisy:

```text
## Symbols
Interface RuntimeContext:80-86
Class TaskController:140-503
  Method checkSpawnAllowed:147-166
  Method execute:244-502
    Constant agent:308-308
    Constant message:282-282
    Function errors.map() callback:277-277
```

Problems:

- `RuntimeContext` does not show its fields.
- Methods do not show parameters or return types.
- `execute` contains local constants and callback noise.

## Desired Behavior Example

Improved output should show declarations and structural shape:

```text
## Symbols
export interface RuntimeContext:80-86 {
  parentAgentId?: string
  depth: number
  rootMaxDepth: number
  canSpawn?: string[]
  store?: MetadataAdapter
}

export class TaskController:140-503
  static checkSpawnAllowed(runtime: RuntimeContext, agentName: string): SpawnDecision:147-166
  execute(params: TaskExecuteParams, context: TaskExecuteContext): Promise<TaskResult>:244-502
```

Key properties:

- Interface shape is visible.
- Method signatures are visible.
- Local constants and callbacks inside method bodies are hidden.
- Method bodies are not shown.

## Language Scope

The first complete Tree-sitter overview renderer targets **TypeScript/TSX**.

Python and other languages are not partially reimplemented in this PRD. Until a language has a complete enough overview query/renderer, it uses the existing LSP Symbols fallback. The implementation should nevertheless be designed as a multi-language abstraction from the start: adding a new language should primarily mean adding a vendored overview query and only small unavoidable language-specific helpers.

JavaScript/JSX, Python, Rust, etc. are future additions unless they fall out trivially from the TypeScript/TSX implementation and are covered by tests.

## Public Tool Contract

`get_document_overview` remains a single-file overview tool.

Parameters:

- `relative_path` (string, required) — source file path relative to project root.
- `depth` (number, optional, default `0`) — nested overview-entry depth. It never opens executable function/method bodies.
- `categories` (string array, optional) — universal overview-entry categories to include.
- `visibility` (`"all" | "public"`, optional, default `"all"`) — visibility filter for overview entries and shape members.
- `max_matches` (number, optional, default unlimited) — maximum number of normal overview entries to render. Shape members do not count toward this limit.

Remove `kinds` from `get_document_overview`. LSP `SymbolKind` compatibility is not a product requirement for this experimental tool. The filter vocabulary should be language-neutral and aligned with the Tree-sitter overview query contract, not raw Tree-sitter node types and not LSP kinds.

### Categories

Public categories are universal and language-neutral:

```text
module, namespace, class, interface, type, enum, function, method, constructor, field, constant, variable
```

Default categories:

```text
module, namespace, class, interface, type, enum, function, method, constructor, field, constant
```

`variable` is excluded by default.

`categories` controls normal overview entries only. Shape members remain controlled by shape rendering defaults and caps. For example, `categories: ["interface"]` should still render the fields inside an interface shape preview.

### Visibility

`visibility` has two values:

- `all` — render all matching overview entries and shape members.
- `public` — render only exported/importable/public entries where the language renderer can determine that reliably.

Default: `all`.

For TypeScript/TSX:

- Top-level public symbols are inline `export`/`export default` declarations or local declarations exported by an export list such as `export { helper }`.
- Class members are public when they have no visibility modifier or an explicit `public` modifier.
- `private`, `protected`, and `#private` class members are hidden under `visibility: "public"`.
- Interface/type/enum members are generally public unless syntax indicates otherwise.

For LSP fallback languages, do not try to reimplement full category/visibility semantics. Fallback is a safety net, not a second complete renderer.

## Output Semantics

### Source-Faithful Declaration Rendering

Render declarations from source text, compacted for readability, with implementation bodies stripped or collapsed.

Examples:

```ts
export async function loadMetadata(
  sessionPath: string,
  options?: LoadOptions,
): Promise<MetadataFile> {
```

Should render as:

```text
export async function loadMetadata(sessionPath: string, options?: LoadOptions): Promise<MetadataFile>:467-479
```

```ts
export const loadMetadata = async (
  sessionPath: string,
): Promise<MetadataFile> => {
```

Should render as a function overview entry while preserving const/arrow syntax:

```text
export const loadMetadata = async (sessionPath: string): Promise<MetadataFile> =>:467-479
```

Source-faithful does not require byte-for-byte formatting. The renderer may normalize whitespace, collapse simple multi-line declarations, and remove trailing semicolons/commas from shape members. It should preserve semantically important tokens such as `export`, `default`, `async`, `static`, `abstract`, generics, inheritance clauses, parameter names/types, return types, optional markers, and default values where part of the declaration.

Doc comments, JSDoc, and docstrings are out of scope for v1.

### Constants and Callable Consts

Top-level consts whose initializer is callable are categorized as `function` entries because that is most useful for agent overview. They are rendered with their actual source syntax.

Plain top-level constants are categorized as `constant` entries. Show initializer values only when they are primitive or short/simple. Collapse large object/array/function initializers to bounded summaries such as `{ ... }`, `[ ... ]`, or a stripped callable header.

Local constants inside function/method bodies are hidden by default.

### Shape Previews

Shape previews are compact structural summaries rendered inside or alongside owning overview entries. Shape members are not normal overview entries.

Default shape behavior:

- Expand one structural level.
- Do not recursively expand referenced types.
- Cap members per shape, with an explicit omitted-member count.
- Use an internal shape member cap, suggested default 8–12.

Example cap:

```text
export interface GiantConfig:10-240 {
  model?: string
  tools?: string[]
  depth?: number
  canSpawn?: string[]
  extensions?: string[]
  reasoningEffort?: string
  description: string
  systemPrompt: string
  ... 17 more members
}
```

Shape options are internal/defaulted in v1. Do not expose public `include_shape`, `shape_depth`, or `shape_member_limit` parameters yet.

### Interfaces

Render direct interface members as shape preview lines:

- property signatures
- method signatures
- index signatures where feasible
- call signatures where feasible

Interface members should not appear as standalone overview entries by default.

### Enums

Render enum members as shape preview lines:

```text
export enum AgentScope:10-14 {
  Bundled = "bundled"
  User = "user"
  Project = "project"
}
```

Enum members should not appear as standalone overview entries by default.

### Type Aliases

For v1, render type alias shape from source declaration/RHS, capped, rather than deeply parsing all TypeScript type grammar into separate member lines.

Example:

```text
export type SpawnDecision:10-12 =
  | { allowed: true }
  | { allowed: false; reason: string }
```

Large or complex aliases may be capped/truncated, but output should remain source-derived.

### Classes and Duplication Rule

Class members can be represented in two ways:

- compact class shape preview at `depth: 0`
- child overview entries at `depth >= 1`

Do not render both for the same class in the same output.

At `depth: 0`:

```text
export class TaskController:140-503 { static checkSpawnAllowed(...), execute(...), static kind: string }
```

At `depth >= 1`:

```text
export class TaskController:140-503
  static checkSpawnAllowed(runtime: RuntimeContext, agentName: string): SpawnDecision:147-166
  execute(params: TaskExecuteParams, context: TaskExecuteContext): Promise<TaskResult>:244-502
```

Class member entries may include:

- constructors
- methods
- fields/properties
- static members
- getters/setters
- abstract members

Visibility applies to class shape previews and child entries.

### Depth

`depth` controls nested overview entries only.

- `depth: 0` renders module-level overview entries only, plus structural shape previews.
- `depth: 1` renders class members as child overview entries.
- `depth` never causes traversal into executable function/method bodies.

Shape previews are independent of `depth`.

### Locality and Noise Filtering

The renderer should classify by lexical context, not symbol kind alone.

Allowed by default:

- module-level declarations
- exported/importable declarations according to `visibility`
- top-level constants and callable consts
- class members when permitted by `depth`
- structural shape members inside interfaces/types/enums/classes

Hidden by default:

- local constants and variables inside executable bodies
- local functions inside executable bodies
- anonymous callbacks
- callback parameters and locals
- object-literal properties in implementation/config values
- arbitrary object/array literal internals in value expressions
- framework-specific call-expression symbols such as `describe`, `it`, or `test`
- JSX element symbols

Implementation should use suppression ranges for executable bodies and implementation value literals. Structural ranges are separate and allowed to produce shape members.

### Re-exports

Re-exports are not Symbols entries in v1:

```ts
export { Foo } from "./foo";
export type { Bar } from "./bar";
```

They remain represented through the current Imports behavior. A dedicated Exports/Re-exports section is out of scope.

## Imports Section

The Imports section keeps current hybrid behavior:

- Tree-sitter parses import/re-export syntax.
- Filesystem/module-path heuristics scope or verify relative/internal module candidates.
- LSP symbol resolution provides imported-name definition locations when available.
- Classification and locations remain best-effort.

This PRD does not replace import definition resolution with a full Tree-sitter export resolver.

## Tree-sitter Overview Query Architecture

Do not rely on upstream `tags.scm` as complete. Coverage varies by grammar, including major grammars.

Instead, define a project-owned overview query contract and vendor per-language `.scm` files. Mature ecosystem queries, especially Aerial's TypeScript outline queries, may be used as inspiration or bootstrap material where licensing permits, but the bridge owns its queries and capture contract.

The generic extraction engine should operate on shared capture names and ranges, not language-specific node type strings. Language-specific Python adapters are allowed only for behavior that cannot be expressed cleanly in queries and should remain small.

Recommended capture vocabulary for overview queries:

- normal definition captures: `@definition.function`, `@definition.class`, `@definition.interface`, etc.
- member captures: `@member.method`, `@member.field`, `@member.enum_member`, etc.
- associated captures: `@name`, optional `@body`
- suppression captures may be added for executable bodies and implementation literals if useful.

Concrete `.scm` structure is an implementation detail, but it must support the public category/shape/depth/visibility semantics above.

Important rules:

- Use semantic capture names rather than query metadata such as `#set! "kind"`.
- Use match-grouped extraction where feasible.
- A definition/member match should have exactly one semantic capture and exactly one `@name`; `@body` is optional but must not be ambiguous.
- `@body` means implementation range to strip/collapse, not shape.
- Shape/member captures are assigned to the nearest containing structural owner by byte-range containment.
- Query files should avoid duplicate normal definition captures; extractor may still defensively deduplicate.
- Query contract violations fail tests hard.

At runtime, structural query/renderer failure causes whole Symbols-section fallback to the current LSP renderer.

## Fallback Behavior

Fallback is whole-section, not per-symbol.

If a Tree-sitter overview renderer/query exists and succeeds, the entire `## Symbols` section uses Tree-sitter output consistently.

If the renderer is unavailable, the parser/query cannot load, or the query contract fails structurally, the entire `## Symbols` section falls back to the existing LSP-based symbol renderer.

Fallback uses existing default LSP overview behavior. It does not attempt to fully honor `categories` or `visibility`.

The tool should not fail merely because Tree-sitter overview rendering is unavailable. It should fail only for ordinary hard errors such as invalid `relative_path` or unreadable files.

## Performance and Bounds

`get_document_overview` must remain fast and bounded.

The implementation should:

- avoid full-project semantic/reference work for Symbols rendering
- avoid calling LSP references as part of overview rendering
- parse only the target file for Tree-sitter Symbols rendering
- cap shape members and large source snippets
- keep `max_matches` scoped to normal overview entries only
- use an internal emergency output cap for pathological files
- preserve current best-effort import resolution behavior without expanding it into full export analysis

## Implementation Slices

1. **Architecture skeleton**
   - Add `bridge/overview/` modules for normalized model, query extraction, rendering, and fallback orchestration.
   - Keep current LSP symbol renderer available as fallback.

2. **TypeScript/TSX query renderer**
   - Add vendored overview `.scm` query files.
   - Extract definitions, names, bodies, suppression ranges, and members.
   - Implement declaration compaction and locality filtering.

3. **Shape previews**
   - Interface member previews.
   - Enum member previews.
   - Type alias source/RHS previews with caps.
   - Class compact shape at `depth: 0` and child entries at `depth >= 1`.

4. **API changes**
   - Remove `kinds` from `get_document_overview`.
   - Add `categories` and `visibility` to `tool-contracts.json`, `schemas.ts`, CLI, and documentation.
   - Update prompt/tool descriptions to explain categories and fallback limits.

5. **Tests/regression**
   - Unit tests for query extraction and contract validation.
   - Fixture tests for TypeScript/TSX output.
   - Fallback tests for unsupported languages/query failure.
   - JSONL regression updates for public tool behavior.

## Testing Decisions

Tests should assert external overview behavior and query contract guarantees, not incidental parser implementation details.

### TypeScript/TSX Coverage

Add fixture-based tests covering:

- source-copied function declarations
- async functions
- generic functions/classes
- function return types
- callable consts categorized as `function` and rendered with const/arrow syntax
- plain top-level constants categorized as `constant`
- short constant initializers shown and large object/array initializers collapsed
- class declarations with modifiers, generics, `extends`, `implements`
- constructors, methods, fields, static members, getters, setters, abstract members
- interface shape previews with properties and method signatures
- enum shape previews with members
- type alias source/RHS preview and capping
- `export default`
- inline exports and `export { localName }` public detection
- `visibility: public` filtering of top-level declarations and class members
- `visibility: all` showing internal/private members when otherwise selected
- local constants/functions/callbacks hidden by default
- object-literal implementation/config properties hidden by default
- class method duplication avoided between compact shape and child entries
- `depth` controlling class child entries but never method-body traversal
- `categories` filtering overview entries while preserving shape members for included structural parents
- `max_matches` truncating overview entries without counting shape members
- large shapes showing omitted-member counts
- TSX parsing where it shares the same declaration patterns; JSX elements are not overview symbols

### Fallback Coverage

Add tests confirming:

- unsupported language or missing renderer falls back to existing LSP Symbols output
- query contract failure fails unit tests
- runtime query/renderer structural failure falls back whole Symbols section rather than mixing per-symbol styles
- fallback remains best-effort and does not promise category/visibility semantics

## Out of Scope

- Reference/xref output in `get_document_overview`
- LSP call hierarchy or call graph generation
- Full Tree-sitter export resolver for import definition locations
- Replacing the current Imports section semantics
- Python or other language-specific overview renderers in this PRD
- Recursive expansion of referenced types by default
- Showing local variables/constants/functions inside executable bodies by default
- Framework-specific test block outlines
- JSX element outlines
- Rendering doc comments, JSDoc, or docstrings by default
- Public shape-rendering knobs before defaults are validated

## Further Notes

Guiding principle:

> The overview should show module structure and API shape, not implementation noise.

The highest-value implementation pieces are:

1. Query-contract-first Tree-sitter rendering for TypeScript/TSX.
2. Source-faithful declarations/signatures.
3. Curated shape previews.
4. Strict locality filtering that avoids executable-body noise.
5. Whole-section LSP fallback for unsupported languages or renderer failures.
