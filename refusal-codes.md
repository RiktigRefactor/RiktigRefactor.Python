# Refusal codes

The Python tool defines its own refusal codes; the [specification](https://github.com/RiktigRefactor/riktigrefactor.spec) does not list any, except `internal-verification-failed`.
This file is the source of truth for them, and `src/riktigrefactor/protocol.py` defines the shared ones in code.
Codes are stable, and messages may change.
A new code is listed in the release notes.
Refactorings add their own codes to the table, each prefixed with the refactoring's name in its meaning.

| Code | Meaning |
|---|---|
| `no-symbol` | There is no symbol at the cursor. |
| `invalid-selection` | The position or range is not in the file, or the selection is not one the refactoring accepts. |
| `file-not-found` | The file is not a Python file of the workspace, or the workspace directory does not exist. |
| `file-not-parseable` | A file of the workspace does not parse. |
| `unsupported-encoding` | A file of the workspace is not UTF-8. |
| `ambiguous-module-name` | Two files of the workspace have the same module name, such as `a.py` and `src/a.py`. |
| `unsupported-scoping` | The scope analysis cannot model a construct, or disagrees with CPython's symbol table. |
| `not-implemented` | The refactoring is not implemented yet. |
| `unsupported-position` | Extract IIFE: the selection is where a lambda or def cannot go or would change meaning: in an f-string, a match pattern, an annotation, a definition with type parameters, or the callee of a call with keyword arguments. |
| `non-local-control-flow` | Extract IIFE: the selection contains `return`, or a `break` or `continue` that leaves it. |
| `yield-in-selection` | Extract IIFE: the selection contains `yield` or `yield from`. |
| `await-in-selection` | Extract IIFE: the selection contains `await`, `async for`, `async with`, or an async comprehension. |
| `super-or-class-cell` | Extract IIFE: the selection uses zero-argument `super()` or `__class__`. |
| `dynamic-class-namespace` | Extract IIFE: an expression is in a class body whose namespace the analysis cannot fully see: the class has a keyword such as `metaclass=` or a base that is not a builtin or a plain class of the file, the body uses `locals`, `vars`, `eval`, `exec`, or `dir`, or the expression reads `__qualname__` or `__module__`. |
| `dynamic-scope-access` | Extract IIFE: the selection uses `locals`, `vars`, `globals`, `eval`, `exec`, or `dir`; or statements are in a function that uses them; or in a module that uses names by spelling. |
| `nonlocal-or-global-write` | Extract IIFE: the selection contains a `global` or `nonlocal` declaration, or assigns a module global or a variable of an enclosing function from inside a function. |
| `walrus-crosses-boundary` | Extract IIFE: an expression assigns a variable with `:=`, which the lambda would bind itself. |
| `deletes-outer-variable` | Extract IIFE: the selection deletes a variable that exists outside it. |
| `expression-is-assignment-target` | Extract IIFE: the selected expression is assigned to or deleted, so it is not a value. |
| `possibly-unbound-variable` | Extract IIFE: a variable that the selection needs, or that it assigns only on some paths and the function reads afterwards, might not be assigned, so passing it would fail earlier. |
| `writes-lost-on-exception` | Extract IIFE: the statements assign a variable the function reads afterwards, inside a `try` body, a `try` that has a finally clause, or a `with` body that could observe the assignments an exception would lose, and an exception can leave the selection after an assignment. |
| `closure-captures-variable` | Extract IIFE: a function created in the selection uses a variable that changes (assigned again, in a loop, or deleted, or bound by `except ... as`), so a copy could go stale. |
| `closure-observes-written-variable` | Extract IIFE: a function defined outside the selection uses a variable that the selection assigns and that function could run during it. |
| `variable-written-by-closure` | Extract IIFE: a nested function assigns a variable that the selection uses, so reading it before the selection runs could see an old value. |
| `declaration-escapes` | Extract IIFE: the statements define a function or class that the rest of the function uses (at module level, any); or, at module level, contain an annotated assignment or a `from __future__` import. |
| `statements-in-class-body` | Extract IIFE: the statements are directly in a class body, where a def would become a method; select an expression instead. |
| `docstring-in-selection` | Extract IIFE: the selection includes a docstring, which would stop being one. |
| `module-variable-visible-elsewhere` | Extract IIFE: module-level statements assign a variable that a function or another module also uses, and the statements could run code that sees it. |
| `star-import-in-selection` | Extract IIFE: the selection contains `from m import *`. |
| `not-renameable` | Rename: the name is a builtin, comes from outside the workspace, is a module (including a name bound by plain `import m`), or is not defined. |
| `attribute-not-supported` | Rename: the name is an attribute of a class or object (anything reached with `obj.name`, or bound in a class body); Rename supports names only. |
| `invalid-identifier` | Rename: the new name is not an identifier, is a keyword, is not NFKC-normalized, or a soft keyword that changes how the program parses. |
| `runtime-protocol-name` | Rename: the old or the new name is a dunder name (`__x__`), which Python looks up by spelling. |
| `private-name` | Rename: the old or the new name starts with two underscores, so Python mangles it inside classes. |
| `binding-would-change` | Rename: after the rename a name would refer to something else (a capture, an un-shadowing, or a merge of two variables), the result would not compile, or a class-body name is looked up in the class and the global scope. |
| `dynamic-access-possible` | Rename: `eval`, `exec`, `compile`, `locals`, `vars`, `globals`, `from m import *`, `getattr` and its relatives with the old or the new name, frames, `import __main__`, `dir()`, or `module.__dict__` may use the name by its spelling. |
| `keyword-callee-unknown` | Rename: the cursor is on a keyword argument whose callee cannot be determined, so the parameter it names is unknown. |
| `parameter-keyword-use-possible` | Rename: the parameter may be passed by keyword by a call that cannot be traced (a method, lambda, decorated function, or function used as a value), or by a call that uses `**` unpacking. |
| `dunder-all-not-analyzable` | Rename: the module's `__all__` is not a list or tuple of plain string literals changed with `=`, `+=`, `.append`, and `.extend`, so the strings that name the renamed name cannot be found. |
| `string-names-symbol` | Rename: a string or template string that the program can observe as source text names the symbol: an f-string `=` field whose text cannot be copied safely, a template string interpolation, or a string annotation. |
| `internal-verification-failed` | The tool's own check of its result failed. This is a bug in the tool; please report it. |
