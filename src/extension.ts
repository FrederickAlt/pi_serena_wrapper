import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { SerenaBridgeClient } from "./bridge-client.js";
import { serenaToolNames, toolDescriptions, toolSchemas, type SerenaToolName } from "./schemas.js";

type ExecuteArgs = {
  signal: AbortSignal | undefined;
  ctx: { cwd: string };
};

function isAbortSignalLike(value: unknown): value is AbortSignal {
  return !!value
    && typeof value === "object"
    && "aborted" in value
    && typeof (value as any).aborted === "boolean"
    && typeof (value as any).addEventListener === "function";
}

function isContextLike(value: unknown): value is { cwd: string } {
  return !!value && typeof value === "object" && typeof (value as any).cwd === "string";
}

function normalizeExecuteArgs(onUpdateArg: unknown, ctxArg: unknown, signalArg: unknown): ExecuteArgs {
  if (isContextLike(signalArg)) {
    return {
      signal: isAbortSignalLike(onUpdateArg) ? onUpdateArg : undefined,
      ctx: signalArg,
    };
  }

  if (isContextLike(ctxArg)) {
    return {
      signal: isAbortSignalLike(signalArg) ? signalArg : undefined,
      ctx: ctxArg,
    };
  }

  throw new Error("Invalid tool execution context");
}

function textResult(tool: SerenaToolName, result: unknown) {
  const text = typeof result === "string" ? result : JSON.stringify(result, null, 2);
  return {
    content: [{ type: "text" as const, text }],
    details: { tool, result },
  };
}

function cancelledToolResult() {
  return {
    content: [{ type: "text" as const, text: "Cancelled" }],
    details: { cancelled: true },
  };
}

const serenaPromptGuidelines = [
  "Call Serena LSP tools as pi tools by their exact underscore names; do not try to run Serena CLI commands such as `serena tools get-symbols-overview`.",
  "A Serena symbol is a named language-server code entity such as a class, function, method, interface, field, or variable; name_path is Serena's path to that entity in the symbol tree, not arbitrary source text.",
  "Use get_symbols_overview to inspect top-level symbols in a file before searching more narrowly.",
  "Use find_symbol to retrieve a known symbol by Serena name path, optionally with children.",
  "Use get_symbol_from_snippet to convert a concrete source occurrence into Serena-style relative_path and name_path values.",
  "If get_symbol_from_snippet returns no matches but includes unresolved and locations, the LSP resolved the occurrence but it could not be converted to a Serena project symbol; inspect locations with native read tools if needed.",
  "Use find_referencing_symbols to find references to a symbol defined in a specific file.",
  "Use get_symbol_from_snippet with resolve type_definition on a variable or expression when you need the concrete type/class/interface behind that occurrence.",
  "If get_symbol_from_snippet returns multiple matches, inspect the returned body_location values with native read tools or retry with a more specific code_snippet.",
  "Use find_implementations to find concrete implementations of interface or abstract method symbols; this depends on active language server support and may report that the operation is unsupported.",
  "Use rename_symbol only when the user wants a real project mutation, because it applies the rename directly and may be rejected by the language server if the workspace has errors.",
];

export default function (pi: ExtensionAPI) {
  const clients = new Map<string, SerenaBridgeClient>();

  function clientFor(cwd: string): SerenaBridgeClient {
    let client = clients.get(cwd);
    if (!client) {
      client = new SerenaBridgeClient();
      clients.set(cwd, client);
    }
    return client;
  }

  for (const name of serenaToolNames) {
    pi.registerTool({
      name,
      label: name,
      description: toolDescriptions[name],
      promptSnippet: toolDescriptions[name],
      promptGuidelines: serenaPromptGuidelines,
      parameters: toolSchemas[name],
      async execute(_toolCallId, params, signalArg, onUpdateArg, ctxArg) {
        const { signal, ctx } = normalizeExecuteArgs(onUpdateArg, ctxArg, signalArg);
        if (signal?.aborted) return cancelledToolResult();

        try {
          const result = await clientFor(ctx.cwd).callTool(ctx.cwd, name, params as Record<string, unknown>, signal);
          return textResult(name, result);
        } catch (error) {
          if (error instanceof Error && error.message === "aborted") return cancelledToolResult();
          throw error;
        }
      },
    });
  }

  pi.on("session_shutdown", async (_event, ctx) => {
    const client = clients.get(ctx.cwd);
    if (client) {
      await client.shutdown();
      clients.delete(ctx.cwd);
    }
  });
}
