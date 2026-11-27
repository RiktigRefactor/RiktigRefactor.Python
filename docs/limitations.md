# Refusals and limitations

Each refusal has a code, listed in [refusal-codes.md](../refusal-codes.md).

See [limitations](https://github.com/RiktigRefactor/riktigrefactor.spec/blob/main/limitations.md) for what is out of scope, such as reflection, serialization by name, and updating comments and strings.

## Rename

- Rename covers names only: locals, parameters, functions, classes, and module-level names, including through imports of workspace modules.
  Attributes, methods, and fields of classes and instances, which are reached with `obj.name`, are not renamed and are refused with a code.
- Names that Python looks up by spelling at run time are not followed: `globals()`, `locals()`, `vars()`, `getattr` and its relatives, `eval`, `exec`, `__all__`, `from m import *`, and keyword arguments forwarded through `**kwargs` or `functools.partial`.
  The tool refuses where it can detect them; see the refusal codes.
- Names in string annotations and other strings are not changed.
- Only the files of the workspace are changed; code outside it that imports the workspace is not seen.
  Renaming a module-level name changes the attribute of the module that other code outside the workspace may use, and renaming a parameter changes what callers outside the workspace must pass by keyword.
- The `__name__` and `__qualname__` of a renamed function or class change, and so do tracebacks, `repr`, and `inspect.signature`.
  A program that reads them can behave differently; the tool does not check for that.
- Names read with `getattr` and its relatives are found only when the name is a string literal that equals the old name; a name computed at run time is not seen, and `dir()`, `sys.modules`, and `importlib` are not followed.
- `getattr(Name, "x")` is accepted when `Name` is bound only by `class` statements.
- Parameters of methods, lambdas, decorated functions, and functions used as values cannot be traced; Rename accepts them only when no keyword argument with that name, and no `**` call, exists in the workspace.
  Any `**` call in the workspace therefore blocks renaming such a parameter.
- A name that is bound in a class body and also read there, such as `x = x + 1` in a class body when `x` is also global, is refused: whether the read finds the class name or the global one depends on timing.
- A self-documenting f-string, `f"{qq=}"`, prints the source text of its expression, so renaming `qq` rewrites it to keep its output: `f"qq={zz!r}"` (a format spec keeps `format`, `!s` and `!a` are kept).
  Text that cannot be copied into the literal part (it has a quote, a backslash, or a line break) and an `=` field inside a format spec are refused (`string-names-symbol`).
  A renamed name in a template string's interpolation is refused too, because `Interpolation.expression` is source text.
- String annotations are evaluated by name later (`typing.get_type_hints`, `dataclasses`), and Rename does not rewrite them: a global rename is refused when any string inside an annotation contains the old or the new name as a word (`string-names-symbol`).
  Under `from __future__ import annotations` the annotations are code and are renamed, but `__annotations__` then holds the new spelling, and the names in `__type_params__`, `inspect.signature`, and `inspect.getmembers` change with the rename; the tool does not check for programs that read them.
- Reflection that can reach the names of any module is refused for module-level names: `eval`, `exec`, and `compile` anywhere in the workspace, frames (`sys._getframe`, `inspect.currentframe`, `f_locals`, `f_globals`, `f_back`, `__globals__`), `builtins.globals` and the like, and `import __main__` when the renamed module may be the entry point.
  `locals()`, `vars()`, and `dir()` without arguments count as `locals()`, including inside comprehensions (which share the function's variables) and in nested functions that read the variable.
  `sys.modules`, `importlib`, and `unittest.mock.patch` are not followed when renaming; for finding the callee of a keyword argument they count as rebinding any global.
- Module globals can be rebound from outside (`lib.f = ...`, `setattr(lib, ...)`, `globals()[...] = ...`, a module passed around as a value): such a function is not singly defined, so its keyword arguments go to an unknown callee and a parameter that is passed by keyword is refused.
- A global of a package's `__init__` whose old or new name is also a submodule of that package is refused (`binding-would-change`), because importing the submodule binds the same attribute.
- The names of the strings given to `getattr`, `setattr`, `hasattr`, and `delattr` are checked against the new name too, since `hasattr(lib, "new")` would change its answer.
- `__all__` is updated only when it is a list or tuple of plain string literals changed with `=`, `+=`, `.append`, and `.extend`.

## Extract IIFE

- Statements become a nested `def`, so their `__qualname__` gains `<locals>` parts (and so does that of a lambda or function defined inside an extracted expression), which shows in `repr` and in `pickle` by name.
  A function or class that is defined in the statements and used after them is refused for the same reason.
- Extracting statements adds one local name, `_extractedN`, to the function (a global at module level).
  Code that lists names, such as `locals()`, `vars()`, `dir()`, `eval`, and `exec`, could see it, so the tool refuses where the function uses them.
  Traceback frames also show the new function.
- The tool refuses when a variable it would pass might not be assigned (it cannot prove an assignment through a loop that may not run, a `with` block that may swallow an exception, or an `if` without `else`), even when the original code would never read it on that path.
- When statements assign a variable that the function reads afterwards, they are refused inside a `try` body, a `try` clause that a finally clause follows, or a `with` body, unless the only assignment is the last step of the selection (see [Extract IIFE](extract-iife.md)).
  An except clause body with no enclosing `try` or `with` is fine.
- A variable of an enclosing function that a nested function assigns (`nonlocal`) is refused when the selection uses it, because arguments are read before the selection's own code runs.
- A variable used by a function created in the selection must be assigned at most once, before the selection and outside any loop that contains it, and never deleted or bound by `except ... as`; otherwise the function would see a copy.
- Statements directly in a class body are refused; select an expression there instead.
- At module level, statements are accepted only when no function and no other module uses a variable they assign (unless they only copy constants and names into plain names), and the module does not use names by spelling (star imports, `__all__`, `globals()`, `eval`).
  Every variable they bind is returned and assigned again, because it is a module attribute; the order in which the attributes first appear in `vars(module)` follows the order of first assignment in the text.
  A module-level loop variable or a conditionally assigned name that is not yet bound is refused, because it cannot be returned when it is unbound.
  Module-level and class-level annotated assignments and `from __future__` imports are refused.
- Expressions in a class body are refused when the class has a keyword such as `metaclass=`, or a base that is not a builtin class or a plain class of the same file, or the body uses `locals`, `vars`, `eval`, `exec`, or `dir`, or the expression reads `__qualname__` or `__module__`.
  A metaclass that a plain-looking workspace base inherits is also a risk when it defines `__prepare__`; the tool follows workspace bases only, which are plain unless they have keywords, so this applies to a base that gets its metaclass from somewhere the tool does not follow (a rare case, and not detected for classes whose bases it cannot see).
- A free variable of an enclosing function that is assigned after the nested function is defined is passed only in straight-line expressions; anything with a call, `and`, `or`, a conditional, or a comprehension is refused.
- A statement that follows another after `;`, or that is the one-line body of a compound statement (`if c: x = 1`), is refused as not a selection.
- An import in the statements that the rest of the function uses is returned like a variable; a later Rename sees the name as a variable instead of an import alias.
- Comment lines above the first selected statement, and after the last, stay where they are; comments between and trailing comments move with the statements.
- Generic functions and classes (type parameters), annotations, type aliases, and match patterns are not supported positions, and neither is anything inside an f-string or a template string (the `=` specifier shows the source text).

## Batch

- Renames are applied first, and verified together on the original files; then each Extract IIFE runs again, in file and position order, on the result of the edits before it, with all its checks and its own verification.
  So the combined result is checked step by step rather than by one final comparison with the original files.
- A selection that contains another action's extraction, or that overlaps it, is refused (`batch-edits-overlap`), even where applying one after the other would be fine.
- Two renames of the same name are refused as an overlap, even when they ask for the same new name.
- A rename that is refused alone because its new name collides is accepted only when the renames it shares names with (as in a swap or a rotation) make the combination pass; otherwise it keeps its own `binding-would-change`.
- When several renames together fail the re-binding check, the later ones are refused one by one, so which action of an interacting group is refused depends on the order of the lines.
- An extraction's generated name (`_extractedN`) can differ from the one it gets alone, because another extraction in the same scope may take a number first.

## The semantic model

- The scope analysis is the tool's own, written from the Language Reference and cross-checked against CPython's `symtable`; it refuses a file where the two disagree.
- Which scopes annotations are evaluated in depends on the Python version (annotation scopes exist from Python 3.14, unless `from __future__ import annotations` is used), and the tool follows the interpreter that runs it.
- Imports are resolved from the workspace's paths alone: a module that is importable only because of `sys.path` changes, a script's own directory, or an installed package that shadows a workspace module is not seen.
- Source files must be UTF-8.
