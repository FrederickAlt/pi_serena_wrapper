# PRD: Improve Document Overview Signal-to-Noise

## Problem Statement

`get_document_overview` is useful for fast orientation because it shows imports, local symbols, and line ranges. However, the current output is not yet precise enough for implementation planning:

- It often omits the most useful API details, such as function signatures, class declarations, interface fields, and type shapes.
- It can include implementation noise from inside function/method bodies, such as local constants and anonymous callback symbols.
- It does not clearly distinguish structural API shape from local implementation detail.

As a result, an agent still needs to read full files in cases where a better overview could have provided enough context.

## Solution

Improve `get_document_overview` so it remains fast and bounded while presenting a source-faithful structural summary of a file.

The overview should:

- Copy declarations/signatures directly from source, with bodies stripped.
- Show compact shape previews for structural declarations such as interfaces, type aliases, classes, and enums.
- Hide local implementation symbols inside function/method bodies by default.
- Preserve useful top-level API symbols, including top-level/exported constants.
- Keep symbol-tree nesting depth separate from shape-preview rendering.
- Avoid duplicate method listings when class methods are already rendered as child symbols.
- Fall back gracefully to the current `Kind Name:start-end` rendering if declaration extraction fails.
- Treat visibility/importability labels as best-effort and lower priority than declarations, shape previews, and noise reduction.
- Define how existing filtering and truncation parameters interact with declarations and shape previews.
- Cover common class API members such as constructors, fields, static members, getters, and setters where the language server exposes them.
- Avoid expanding scope into documentation/comment rendering unless explicitly requested later.

References/xrefs are out of scope for this PRD because there is already a dedicated `get_references` tool.

## Current Behavior Example

Example of current noisy/underspecified output:

```text
## Symbols
Interface RuntimeContext:80-86
Class TaskController:140-503
  Method checkSpawnAllowed:147-166
  Method execute:244-502
    Constant agent:308-308
    Constant message:282-282
    Constant message:294-294
    Function errors.map() callback:277-277
```

Problems:

- `RuntimeContext` does not show its fields.
- `checkSpawnAllowed` does not show its parameters or return type.
- `execute` contains local constants and callback noise.

## Desired Behavior Example

With improved declarations and shape previews:

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
- Local constants and anonymous callbacks inside `execute` are hidden.
- Method bodies are not shown.

## User Stories

1. As an agent, I want to see source-faithful function signatures in the overview, so that I can understand APIs without opening the full file.
2. As an agent, I want declarations copied from source, so that modifiers like `export`, `async`, `static`, `abstract`, generics, inheritance, and return types are preserved.
3. As an agent, I want interface fields shown compactly, so that I can understand data shapes quickly.
4. As an agent, I want type aliases with object/function/union shapes summarized, so that important config and data types are understandable.
5. As an agent, I want class declarations to show important modifiers and inheritance, so that I understand the class role quickly.
6. As an agent, I want class methods shown without local method-body variables, so that large classes remain readable.
7. As an agent, I want enum members shown as part of the enum shape, so that enum APIs are visible without standalone noise.
8. As an agent, I want local constants hidden by default, so that implementation details do not drown out file structure.
9. As an agent, I want top-level/exported constants preserved by default, so that public module API is not accidentally hidden.
10. As an agent, I want anonymous callback symbols hidden by default, so that map/filter/reducer internals do not pollute the symbol tree.
11. As an agent, I want large shapes capped with an explicit omitted-member count, so that output stays bounded.
12. As an agent, I want symbol nesting depth to remain separate from shape-preview depth, so that I can control structural traversal independently.
13. As an agent, I want class methods not to be duplicated between class braces and child symbols, so that output is not redundant.
14. As an agent, I want constructors, public fields, static fields, getters, and setters shown when they are part of the class API, so that class shape is not method-only.
15. As an agent, I want overload signatures rendered sensibly, so that overloaded APIs are understandable without duplicate implementation noise.
16. As an agent, I want declaration extraction failures to degrade gracefully, so that overview remains available even when parsing is imperfect.
17. As an agent, I want optional visibility/importability labels where reliable, so that I can distinguish public API from internal helpers.
18. As a tool user, I want default output to be deterministic and bounded, so that I know what kind of information I am seeing.
19. As a tool user, I want `kinds` and `max_matches` to have clear semantics, so that filtering/truncation does not unexpectedly suppress structural shape previews.
20. As a developer, I want the behavior implemented as deep, testable modules, so that language-specific declaration extraction can evolve safely.

## Implementation Decisions

### 1. Source Declaration Extraction

Build or modify a declaration extraction layer that copies symbol declarations from source text and strips the body.

The extractor should prefer source text over reconstructed LSP signatures.

Examples:

```ts
export async function loadMetadata(
  sessionPath: string,
  options?: LoadOptions,
): Promise<MetadataFile> {
```

Should render as either compact one-line output:

```text
export async function loadMetadata(sessionPath: string, options?: LoadOptions): Promise<MetadataFile>:467-479
```

Or a readable multi-line declaration if compacting would harm clarity.

Class example:

```ts
export class AgentRegistry implements AgentDiscoveryAdapter {
```

Should render as:

```text
export class AgentRegistry implements AgentDiscoveryAdapter:210-324
```

Python example:

```py
async def run_task(prompt: str, *, agent: str | None = None) -> TaskResult:
```

Should render as:

```text
async def run_task(prompt: str, *, agent: str | None = None) -> TaskResult:42-80
```

### 2. Fallback Behavior

Declaration extraction must be best-effort.

If the extractor cannot confidently produce a source declaration, the tool should fall back to the existing stable format:

```text
Kind Name:startLine-endLine
```

The overview tool should not fail merely because declaration extraction failed for one symbol.

### 3. Shape Preview Rendering

Shape previews are curated summaries for structural declarations only.

Include shape previews for:

- Interfaces
- Type aliases with object/function/union shape
- Classes, when useful and not duplicative
- Enums

Do not include arbitrary variables in shape previews.

Exclude from shape previews by default:

- Local variables inside functions
- Local constants inside functions
- Anonymous callback locals
- Arbitrary object literals assigned to local variables
- Implementation details inside function/method bodies

Shape preview members are independent from the normal symbol kind filter. For example, `Property` and `EnumMember` may remain excluded from the normal symbol tree while still appearing inside interface/enum shape previews.

### 4. Interface Shape Example

```ts
export interface RuntimeContext {
  parentAgentId?: string;
  depth: number;
  rootMaxDepth: number;
  canSpawn?: string[];
  store?: MetadataAdapter;
}
```

Desired overview:

```text
export interface RuntimeContext:80-86 {
  parentAgentId?: string
  depth: number
  rootMaxDepth: number
  canSpawn?: string[]
  store?: MetadataAdapter
}
```

### 5. Enum Shape Example

```ts
export enum AgentScope {
  Bundled = "bundled",
  User = "user",
  Project = "project",
}
```

Desired overview:

```text
export enum AgentScope:10-14 {
  Bundled = "bundled"
  User = "user"
  Project = "project"
}
```

Enum members should not appear as standalone nested symbols by default if they are already shown inside the enum shape.

### 6. Type Alias Shape Example

```ts
export type SpawnDecision =
  | { allowed: true }
  | { allowed: false; reason: string };
```

Desired overview:

```text
export type SpawnDecision:10-12 =
  | { allowed: true }
  | { allowed: false; reason: string }
```

Large or complex type aliases may be summarized rather than fully expanded, but the output should remain source-faithful where practical.

### 7. Class Shape and Duplication Rule

Avoid duplicate method listings.

If `depth: 0` means class children are not rendered separately, a compact class shape may summarize methods:

```text
export class TaskController:140-503 { static checkSpawnAllowed(...), execute(...) }
```

If `depth >= 1` and class methods are already rendered as child symbols, do not repeat those methods inside class braces:

```text
export class TaskController:140-503
  static checkSpawnAllowed(runtime: RuntimeContext, agentName: string): SpawnDecision:147-166
  execute(params: TaskExecuteParams, context: TaskExecuteContext): Promise<TaskResult>:244-502
```

Do not render this duplicate form:

```text
export class TaskController:140-503 { static checkSpawnAllowed(...), execute(...) }
  static checkSpawnAllowed(runtime: RuntimeContext, agentName: string): SpawnDecision:147-166
  execute(params: TaskExecuteParams, context: TaskExecuteContext): Promise<TaskResult>:244-502
```

For interfaces/types/enums, braces remain useful even when `depth` is nonzero because their members are the structural shape rather than method-body implementation detail.

### 8. Locality Rule

By default, the renderer should not descend into Function or Method bodies when rendering nested symbols.

This is the primary rule for eliminating local implementation noise.

Allowed by default:

- Top-level symbols
- Top-level constants, especially exported/importable constants
- Class/interface/type/enum structural members
- Class methods when requested by symbol nesting depth

Hidden by default:

- Local constants inside function/method bodies
- Local variables inside function/method bodies
- Anonymous callback functions
- Callback parameters and locals
- Block-scoped implementation details

Example hidden noise:

```text
Constant agent:308-308
Constant message:282-282
Function errors.map() callback:277-277
```

### 9. Top-Level Constants vs Local Constants

Do not remove all constants from default output.

Top-level constants can be part of the module API and should still be eligible for rendering, especially when exported.

Example:

```ts
export const DEFAULT_AGENT_SCOPE = "both";
```

Should be eligible for overview output:

```text
export const DEFAULT_AGENT_SCOPE = "both":24-24
```

Local constants inside function/method bodies should remain hidden by default.

### 10. Depth Semantics

Keep the existing `depth` parameter focused on symbol-tree nesting.

`depth` controls traversal such as:

```text
module -> class -> method -> nested symbol
```

`depth` should not be the sole control for shape previews.

Shape previews should have separate internal behavior, for example:

- Shape enabled/disabled
- Shape member limit
- Shape expansion depth

However, avoid exposing unnecessary tool parameters initially. Prefer good defaults. Expose additional knobs later only if there is demonstrated need.

### 11. Shape Bounds

Overview output must remain bounded.

Default shape rendering should:

- Expand only one structural level.
- Avoid recursively expanding referenced types.
- Cap members per shape.
- Show omitted count explicitly.

Example:

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

Suggested default cap: 8–12 members per shape.

### 12. Visibility / Importability

Visibility/importability labels are useful but lower priority than declarations, shape previews, and noise reduction.

They should be best-effort and language-aware.

Examples:

- TypeScript/JavaScript: preserve source syntax such as `export`, `export default`, `private`, `protected`, `readonly`, `abstract`.
- Python: optionally use `__all__` when present; otherwise leading underscore conventions may indicate internal/private-ish symbols.
- Other languages can map their native visibility systems over time.

Do not make fuzzy visibility heuristics a hard requirement for the first implementation.

### 13. Performance and Bounds

`get_document_overview` must remain a fast overview tool.

The implementation should:

- Avoid full-project semantic/reference work.
- Avoid calling LSP references as part of normal overview rendering.
- Prefer local source text, tree-sitter, and already-available document symbols.
- Cap output sizes.
- Fall back gracefully when a parser or language server cannot provide enough information.

### 14. Existing Parameter Semantics

Preserve the mental model of existing parameters while making their interaction with shape previews explicit.

Recommended semantics:

- `depth` controls traversal of the symbol tree only.
- `kinds` filters normal symbol entries only.
- Shape preview members are curated structural details and are not suppressed merely because their LSP kind, such as `Property`, `Field`, or `EnumMember`, is absent from `kinds`.
- Top-level constants remain normal symbol entries, so explicit `kinds` filters may include or exclude them according to the requested kinds.
- `max_matches` limits rendered symbol entries, not individual shape-preview members.
- Shape previews use a separate shape-member cap and omitted-member count.

This keeps filters useful without making interface fields or enum members disappear unexpectedly.

### 15. Class Member Coverage

Class overview should not be method-only when the source exposes other API-relevant members.

When available from document symbols and source extraction, render concise declarations for:

- Constructors.
- Public instance fields/properties.
- Public static fields/properties.
- Getters and setters.
- Abstract methods/properties.
- Private/protected members when they appear in the selected symbol tree, preserving their source modifiers.

Do not descend into constructor or method bodies by default. Class member rendering should describe class API surface, not implementation internals.

### 16. Overloads

Overloaded APIs should be understandable without duplicate noise.

For TypeScript-style overloads:

- Prefer rendering overload signatures when they are present in source and discoverable.
- Avoid rendering the implementation signature as a separate duplicate if it only exists to satisfy overload implementation.
- If overload detection is unreliable, fall back to stable per-symbol rendering rather than guessing.

For languages without overload syntax, no special behavior is required.

### 17. Declaration Formatting and Comments

Source-faithful does not require byte-for-byte formatting.

The renderer may normalize declarations for readability by:

- Collapsing simple multi-line declarations into one line.
- Removing trailing semicolons or commas from shape members.
- Normalizing repeated whitespace.

The renderer should preserve semantically important tokens such as modifiers, decorators where feasible, generic parameters, inheritance clauses, parameter names, parameter types, return types, optional markers, and default values when they are part of the declaration.

Doc comments/JSDoc/docstrings are out of scope for this PRD. They may be useful later, but including them by default would change the overview from structural summary toward documentation extraction.

### 18. Language Scope and Phasing

The design should remain language-neutral, but implementation can be phased.

Recommended phasing:

1. TypeScript/JavaScript support as the first complete implementation target, because the motivating examples and symbol shapes are strongest there.
2. Python support for declaration extraction and locality filtering where the same abstractions apply cleanly.
3. Additional language-specific shape renderers only when there are fixtures and clear formatting rules.

A language without a shape renderer should still benefit from fallback rendering and locality filtering where possible.

## Testing Decisions

Tests should assert external overview behavior, not internal parser implementation details.

### TypeScript Test Coverage

Add fixture-based tests covering:

- Function declarations copied from source.
- Async function declarations.
- Generic function declarations.
- Function return types.
- Class declarations copied from source.
- `export default` declarations.
- `abstract` classes/methods.
- `readonly` fields/properties where rendered.
- Generics on classes and functions.
- `extends` / `implements` clauses.
- Interface shape previews.
- Type alias shape previews.
- Enum shape previews.
- Constructors, fields/properties, static members, getters, and setters where exposed.
- Overloads, including avoiding duplicate implementation signatures when feasible.
- Decorators/modifiers where supported.
- Top-level/exported constants remain visible by default.
- Explicit `kinds` filters can include/exclude top-level constants as normal symbol entries.
- Local constants inside function/method bodies are hidden by default.
- Anonymous callbacks are hidden by default.
- Large shapes are capped and show omitted-member count.
- `max_matches` truncates symbol entries without counting individual shape members.
- Class methods are not duplicated between class shape braces and child symbols.

### Python Test Coverage

If Python support is in scope for the implementation, add fixture-based tests covering:

- Function declarations copied from source.
- Async function declarations.
- Class declarations copied from source.
- Decorated functions/classes.
- Dataclasses.
- Leading underscore conventions.
- `__all__` where practical.
- Local variables hidden by default.

### Depth and Shape Tests

Add tests confirming:

- `depth` controls symbol nesting.
- Shape preview still works at `depth: 0`.
- Shape preview does not descend into function/method bodies.
- Interface/type/enum shapes are not suppressed merely because `Property`, `Field`, or `EnumMember` are excluded from the normal symbol kind filter.

### Fallback Tests

Add tests confirming:

- If declaration extraction fails for a symbol, the overview still renders that symbol using the old `Kind Name:start-end` format.
- One extraction failure does not fail the entire overview.

## Out of Scope

- Full reference/xref output.
- LSP reference summaries inside `get_document_overview`.
- Call graph generation.
- LSP call hierarchy.
- Complete semantic visibility for every language.
- Recursive expansion of referenced types by default.
- Showing all local variables/constants in function/method bodies by default.
- Adding many new public tool parameters before defaults have been validated.
- Rendering doc comments, JSDoc, or docstrings by default.
- Byte-for-byte source formatting preservation.

## Further Notes

The guiding principle is:

> The overview should show module structure and API shape, not implementation noise.

The highest-value implementation pieces are:

1. Source-faithful declarations/signatures.
2. Curated structural shape previews.
3. A strict default locality rule that avoids descending into function/method bodies.
4. Clear bounds and graceful fallback.

These changes should make `get_document_overview` much more useful for planning while preserving the role of dedicated tools like `read` and `get_references` for deeper inspection.
