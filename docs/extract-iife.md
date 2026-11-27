# Extract IIFE

Extract IIFE wraps a selected expression, or whole statements of one block, in an immediately-invoked lambda or nested function that captures nothing from enclosing function scopes: it takes every local it reads as a parameter, and returns every local it writes that the rest of the function reads.

An expression becomes a `lambda`:

```python
# Before
def total_cost(price, qty, shipping):
    subtotal = price * qty
    return subtotal + shipping

# After
def total_cost(price, qty, shipping):
    subtotal = price * qty
    return (lambda subtotal, shipping: subtotal + shipping)(subtotal, shipping)
```

Statements become a nested `def` named `_extractedN` (the first N that the file does not use), defined immediately before its call:

```python
# Before
def step(a, b):
    a += 1
    b = a * 2
    return a, b

# After
def step(a, b):
    def _extracted1(a):
        a += 1
        b = a * 2
        return a, b
    a, b = _extracted1(a)
    return a, b
```

## What is passed and returned

- The parameters are the variables of enclosing functions that the selection reads, in order of first appearance: locals, parameters, variables of enclosing functions, comprehension variables, and (in a class body) class-level names, because a lambda or nested function cannot see them.
- Module globals and builtins are not passed, because Python looks them up by name; a local that shadows one is a local, so it is passed.
- For statements, a variable the selection assigns is returned and assigned back when the rest of the function can read it: anything read after the selection, in a loop that contains the selection, or by a function defined in the function.
  A variable that is only assigned and never read again stays inside.
- A variable that the selection assigns only on some paths is also passed in, so that it keeps its old value on the others.
- Statements at the top level of a module return and re-assign every variable they bind, even one that nothing else reads, because module variables are attributes of the module that other code can see (`getattr`, `vars`, star imports, code outside the workspace).
  They are supported when no function or other module uses such a variable, unless the statements only copy constants and names into plain names, which cannot run other code.
- An import in the statements whose name is used afterwards (at module level, always) returns the name like a variable; the post-edit check is told that this name is no longer an import alias.
  `import a.b` binds `a`, and that is the name returned.
- Statement lines are indented one more level, except lines inside a multi-line string.
  Comments between and after the statements move with them; comment lines above the first selected statement stay where they are.

## Checks

The tool refuses unless it can prove that behavior is preserved.
It runs its own definite-assignment analysis, because passing a variable that might not be assigned yet would fail earlier than the original code did.
After the edit it checks the result in three ways:

1. the edited file compiles;
2. every name outside the edited text still binds to the same symbol;
3. the generated function has no free variables, checked both in the tool's binding model and in CPython's `symtable` (the symbol table's free variables are empty, and the function declares no `global` or `nonlocal` names).

## Refusals

The codes are in [refusal-codes.md](../refusal-codes.md). The selection is refused when:

- it contains `return`, a `break` or `continue` that leaves it, `yield`, `await`, `async for`, or `async with`;
- it uses zero-argument `super()` or `__class__`, or `locals`, `vars`, `globals`, `eval`, `exec`, or `dir`; statements are also refused when their function uses `locals`, `vars`, `eval`, `exec`, or `dir`, because they could see the new local function or the missing assignments;
- it contains a `global` or `nonlocal` declaration, or assigns a variable declared that way, or a variable of an enclosing function;
- an expression assigns with `:=`, deletes, or is itself assigned or deleted; statements delete a variable that is declared outside them;
- a variable it needs might not be assigned yet, including a loop variable after the loop, a variable assigned in only one branch, and a variable assigned in a `with` block (a context manager can swallow the exception).
  The analysis knows that `for`/`else` assigns on every path, that a `match` guard can read the names its pattern captured, that an operand evaluated earlier in the same statement assigned a variable with `:=`, and that a free variable of an enclosing function assigned only after the function was defined can be passed when the expression is a straight line of reads and operators (no calls, no `and`/`or`/conditionals, no comprehensions);
- statements assign a variable that the rest of the function reads, inside a `try` body (with an except or finally clause), an except or else clause of a `try` that has a finally clause, or a `with` body, and an exception could leave the selection after an assignment.
  That cannot happen when the first statement that assigns such a variable is the last statement and its assignment is the final step: a single `name = value`, `a, b = value`, `name += value`, or a one-name import, with no `:=` in it;
- a function created in the selection uses a variable that changes after it was copied (a variable assigned more than once, assigned after the selection or in a loop that holds it, deleted anywhere, or bound by `except ... as`, which unbinds it at the end of the clause); a function outside the selection uses a variable that the selection assigns and the selection could run code (not when it only copies constants and names into plain names); or a nested function assigns a variable the selection uses;
- statements define a function or class that the rest of the function uses (at module level, any), or are at module level and contain an annotated assignment (`x: int = 1` records `__annotations__`), or a `from __future__` import;
- the statements are directly in a class body, include a docstring, or contain `from m import *`;
- an expression is in a class body whose namespace could hold names the analysis cannot see: the class has a keyword (such as `metaclass=`) or a base that is not a builtin class or a plain class of the same file, the class body uses `locals`, `vars`, `eval`, `exec`, or `dir`, or the expression reads `__qualname__` or `__module__`;
- the position cannot hold a lambda: inside an f-string, a match pattern, an annotation, a definition with type parameters, or as the callee of a call with keyword arguments.

## Command

```shell
riktig-py extract-iife --workspace . --file src/order.py --range 12:5-14:20
```

See [the command line](command-line.md) for the options every command accepts.
