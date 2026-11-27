# The semantic model

For the agents that write refactorings; the code is in `src/riktigrefactor/semantics.py`.

`analyze_workspace(workspace)` returns a `WorkspaceBindings`, cached on the workspace.
It holds every identifier occurrence in the workspace.

- An `Occurrence` has its file, its exact span (`start_offset`, `end_offset` in `SourceFile.text`), its `source_name` as written, its `role`, its `scope`, the `ast` `node`, the `symbol` it binds to, and `alternatives`.
- A `Symbol` is `(kind, module, scope path, name)`.
  Module-level names have an empty scope path.
  A scope path is a tuple of `ScopeKey(kind, start_offset)`, so symbols stay comparable between the texts before and after edits.
  `Symbol.name` is NFKC-normalized and mangled (`__x` in class `C` is `_C__x`).
- `SymbolKind`: `BINDING` (a variable, parameter, function, class, or import alias), `BUILTIN`, `MODULE` (a workspace module), `EXTERNAL` (a module or a name imported from outside the workspace), `UNRESOLVED_NAME`, `ATTRIBUTE` (an attribute of anything that is not a workspace module; all attributes with one spelling are one symbol), `KEYWORD_OF_BUILTIN`, and `KEYWORD_OF_UNKNOWN_CALLEE`.
- Where a name is looked up in a class namespace first and an outer scope second (class bodies; annotation and type-parameter scopes inside classes), the occurrence binds to the class symbol and lists the fallback in `alternatives`.
  A refactoring must treat such an occurrence as a reference to all of them.

Queries on `WorkspaceBindings`: `occurrences_in_file`, `occurrences_at_cursor(path, offset)`, `occurrences_of(symbol)`, `binding_occurrences_of(symbol)`, `origin_of(symbol)`, `occurrences_with_origin(origin)`, `dynamic_name_uses()`, and per module `modules[key].scope_of(node)`.

## Imports

A name bound only by an import is an alias of what it imports: `origin_of` follows aliases.
In `from m import x` the span of `x` has two occurrences: `IMPORT_SOURCE_NAME` (a reference to `m.x`) and `IMPORT_BINDING` (the local name).
With `as`, they have different spans.
A name with any other binding, or imports of different things, is not an alias.

## Verification

`verification.verify_edits(workspace, edits, renamed_symbols=...)` applies the edits to a copy, re-parses and compiles it, analyzes it, and checks that every occurrence binds to the same symbol as before (mapping offsets through the edits, and renaming the symbols in `renamed_symbols`).
It also fails when two symbols would merge.
Refactorings that rewrite the edited code freely pass `edited_regions_are_rewritten=True` and must check those regions themselves.
It returns the new workspace or raises `RefusalError` with `internal-verification-failed`.

## Dynamic name uses

`ModuleBindings.dynamic_name_uses` lists constructs that use names by spelling: `star-import`, `dunder-all`, `dynamic-builtin` (`eval`, `exec`, `globals`, `locals`, `vars`, `getattr`, and so on), `dunder-dict`, and `keyword-unpacking-call`.
A refactoring decides which of them make it refuse.
