# Pluggable module-path resolution for import classification

Non-relative Python imports from nested directories (e.g. `bridge/tools/*.py`
importing modules from `bridge/`) were misclassified as `[external]` because
the LSP symbol search was scoped to the importing file's own directory, and
the subsequent verification was too lenient to distinguish same-named files
in unrelated directories. We fixed the scope and added a pluggable
language-specific module resolver with a three-tier classification fallback.

## Considered Options

- **Fix scope only, keep lenient verification**: Widen the LSP search to
  project-wide, but rely on the existing `_verify_module_file_match` (suffix
  match on file stem). Rejected because `endswith("/formatting")` would
  accept `tests/formatting.py` as a valid resolution of `import formatting`
  from `bridge/tools/` — a false positive.
- **Fix scope + strict verification only**: Generate expected file paths from
  the directory hierarchy and reject any resolved file outside that set.
  Rejected because it fails for root-file imports from `sys.path`-added
  directories (e.g. `serena_pi_bridge.py` importing `name_path` → resolved
  to `bridge/name_path.py`, which is not in the file's ancestor chain). No
  pure-path resolver can model runtime `sys.path` without filesystem access.
- **Three-tier fallback (chosen)**: Exact resolver match → lenient
  name-based match → unconditional `[internal]` for unresolvable languages.
  Accepts occasional false positives in the lenient tier rather than risk
  false negatives (classifying an internal module as external).

## Consequences

- New module `bridge/module_resolver.py` with a `ModuleResolver` registry
  and a Python resolver (walk-up-directory-hierarchy heuristic).
- `_resolve_import_location` now collects all candidates on ambiguity
  instead of silently skipping them.
- `_classify_import` has three tiers: resolver exact match, lenient
  `_verify_module_file_match` fallback, and unconditional `[internal]`
  for languages without a resolver.
- v1 ships only a Python resolver; TypeScript gets the unconditional
  fallback (any workspace match → `[internal]`).
- The resolver registry is designed to accept drop-in resolvers for
  additional languages (TypeScript, C, etc.).
