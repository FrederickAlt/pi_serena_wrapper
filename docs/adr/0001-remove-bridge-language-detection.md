# Remove bridge-managed language detection

The bridge's `_ensure_language_for_args` auto-registered a project language on every tool call by matching file suffixes against Serena's `Language` enum. This was removed because it blurred the read/write boundary (queries silently mutated project config), duplicated suffix→language mapping logic that Serena already owns, and had incomplete coverage for extensions like `.tsx` or `.d.ts`. Language registration is now delegated entirely to the user's Serena config.

## Consequences

- Users must ensure the Serena project config includes all language servers they need (e.g., by opening a file of that language in Serena or by configuring the language list explicitly).
- The bridge no longer silently registers a language when a tool touches a file in a previously unregistered language. The LSP call will fail with a clear error if the language isn't configured, rather than succeed while mutating config behind the scenes.
