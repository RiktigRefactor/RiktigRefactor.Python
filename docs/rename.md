# Rename

Rename renames a local, parameter, function, class, or module-level name, and every reference to it across the workspace, including through imports: `from m import x`, `import m; m.x`, and `import m as k; k.x`.
It uses the tool's scope analysis (see [the semantic model](semantic-model.md)), and so follows Python's own rules: function, class, comprehension, lambda, and type-parameter scopes, `global` and `nonlocal`, class bodies whose names are not visible in methods, walrus targets in comprehensions, `except ... as`, and `match` captures.

After renaming, the tool re-parses the result, compiles it, and re-binds every name in the workspace; it refuses if any name would refer to something else (a capture, an un-shadowing, or a merge of two variables).

## What is renamed

- The cursor can be on a declaration or on any reference.
- `from m import x` without `as` binds the name `x` in the importing module to `m.x`; they are one name, so renaming either renames both, in every importer (and through re-exports).
  With `as`, the two are separate: the cursor on `x` in `from m import x as y` renames `m.x` and keeps `y`; the cursor on `y` renames only `y`.
- `m.x` where `m` is a workspace module is a reference to the module-level name `x` of `m`.
- A keyword argument `f(x=1)` is renamed with the parameter when the callee is provably the function (see below).
- The strings of `__all__` that name a renamed module-level name are updated, when `__all__` is a list or tuple of string literals that is changed only with `=`, `+=`, `.append`, or `.extend`; otherwise the rename is refused.
- Other strings, comments, and docstrings are not changed; a string equal to the old name gives the warning `string-matches-name`.

## Parameters and keyword arguments

A parameter's name can be observed by callers that pass it by keyword.
Positional-only parameters (before `/`), `*args`, and `**kwargs` cannot be named by a caller, so they are always safe.
For other parameters:

- if the function is an undecorated `def` that is bound once and used only as the callee of calls (including through imports), every call is known: keyword arguments are renamed, and a call that uses `**` unpacking refuses the rename;
- a function whose module-level name may be rebound from elsewhere (`lib.f = ...`, `setattr(lib, ...)`, `globals()[...] = ...`) counts as an untraced callee;
- otherwise (methods, lambdas, decorated functions, functions used as values) the calls cannot be traced, and the rename is allowed only when no call anywhere in the workspace passes a keyword with that name to an unknown callee and no call uses `**` unpacking; a `**` call whose callee is an unshadowed builtin does not count.

## What is refused

See [refusal-codes.md](../refusal-codes.md) for the codes.

- Attributes, methods, and fields: anything reached with `obj.name` other than a workspace module, and every name bound in a class body (`attribute-not-supported`).
- Builtins, names from outside the workspace, modules (`import m` binds the module name; write `import m as k` first), and names that are not defined (`not-renameable`).
- A new name that is not an identifier, is a keyword, or is not NFKC-normalized (`invalid-identifier`).
  Soft keywords (`match`, `case`, `type`, `_`) are accepted when the result still parses and binds the same.
- Dunder names (`runtime-protocol-name`) and private names that start with two underscores, which Python mangles (`private-name`), as the old or the new name.
- A collision or capture (`binding-would-change`), including a class-body name that is looked up in the class first and then globally.
- Code that may use the name by its spelling (`dynamic-access-possible`): `eval`, `exec`, and `compile` in the name's scope, `locals()` and `vars()` in the same scope, `globals()` and `from m import *` for module-level names, `getattr`, `setattr`, `hasattr`, and `delattr` with the old name as a string, and `module.__dict__`.
- Source text the program can see (`string-names-symbol`): a name in a template string's interpolation, an `=` field of an f-string that cannot be rewritten, and a string annotation that contains the name.
  `f"{qq=}"` is rewritten to `f"qq={zz!r}"` so that its output stays the same.
- A global of a package's `__init__` that has the name of a submodule of the package, before or after the rename (`binding-would-change`).
- A keyword argument whose callee cannot be determined (`keyword-callee-unknown`), and parameters that may be passed by keyword (`parameter-keyword-use-possible`).
- An `__all__` that is built in some other way (`dunder-all-not-analyzable`).

## Command

```shell
riktig-py rename --workspace . --file src/order.py --at 12:5 --new-name count
```

See [the command line](command-line.md) for the options every command accepts.
