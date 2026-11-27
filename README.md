# RiktigRefactor.Python

[![Build and test](https://github.com/RiktigRefactor/RiktigRefactor.Python/actions/workflows/build-and-test.yml/badge.svg)](https://github.com/RiktigRefactor/RiktigRefactor.Python/actions/workflows/build-and-test.yml)
![Status: early development](https://img.shields.io/badge/status-early%20development-orange)

Seriously safe behavior-preserving refactorings for Python.
*Riktig* means "correct" in Swedish/Norwegian.
When the tool cannot prove a transformation is safe, it refuses with a clear reason instead of guessing.

This is the Python implementation of the [RiktigRefactor specification](https://github.com/RiktigRefactor/riktigrefactor.spec).
It uses only the Python standard library: `ast` for syntax and `symtable` for scopes.

## What it can do

The tool has these refactorings:

### Rename

Rename renames a local, parameter, function, class, or module-level name and every reference to it across the workspace, including through imports.

#### Before

```python
def total(items):
    return sum(items)
```

#### After

```python
def grand_total(items):
    return sum(items)
```

See more details in [docs/rename.md](docs/rename.md).

### Extract IIFE

Extract IIFE wraps a selected expression, or whole statements, in an immediately-invoked lambda or function that captures nothing from enclosing function scopes.
Every local it reads becomes a parameter, and every local it writes that the rest of the function reads is returned and assigned back.

#### Before

```python
def step(a, b):
    a += 1
    b = a * 2
    return a, b
```

#### After

```python
def step(a, b):
    def _extracted1(a):
        a += 1
        b = a * 2
        return a, b
    a, b = _extracted1(a)
    return a, b
```

An expression becomes `(lambda subtotal, shipping: subtotal + shipping)(subtotal, shipping)`.

See more details in [docs/extract-iife.md](docs/extract-iife.md).

### Batch

Batch runs several renames and extractions together, with every location referring to the original files.
It is all-or-nothing by default, refuses actions whose edits overlap or that change each other's meaning, and accepts swaps such as `a→b` with `b→a`.
See more details in [the command line](docs/command-line.md#batch).

## Using it

The package is not published yet; from a clone, run `./build-and-test` once, then:

```shell
.venv/bin/riktig-py rename --workspace . --file src/order.py --at 12:5 --new-name count
.venv/bin/riktig-py batch --workspace . actions.jsonl --apply
```

See [the command line](docs/command-line.md) for the options and exit codes, [the library](docs/library.md) for using it from code, and [refusals and limitations](docs/limitations.md).

## Building and testing

```shell
./build-and-test
```

For more information, see [CONTRIBUTING.md](CONTRIBUTING.md).
