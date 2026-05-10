## name_path

   A `/`-separated path in the symbol tree **within a single source file** (e.g.,
   `MyClass/my_method`). It does **not** include a file path.

   `name_path` is always a **pattern**, not an exact identifier. It is matched
   component-by-component, right-to-left, each component exact:
     - `send` matches any symbol whose last component is `send`
     - `MyClass/send` matches any symbol whose last two components are `MyClass`/`send`
     - `/MyClass/send` (absolute, leading `/`) requires an exact full match

   This applies to all tools (`find_symbol`, `find_referencing_symbols`,
   `find_declaration`, `find_implementations`, `rename_symbol`).
