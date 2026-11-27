# Building and testing

Install [Git](https://git-scm.com/) and [Mise](https://mise.jdx.dev/).
Mise provides Python and creates a virtual environment in `.venv`, so nothing else needs to be installed:

```shell
./build-and-test
```

`build-and-test` installs the package and pytest into the virtual environment and runs every test; `build-and-test.cmd` does the same on Windows through Git for Windows' Bash.
Without Mise, in a virtual environment: `python -m pip install -e ".[dev]"` and `python -m pytest`.

The tool needs Python 3.13 or later and has no run-time dependencies: it uses only `ast` and `symtable` from the standard library.
Tests run the programs of the test cases with the same interpreter that runs pytest.

## Test cases

Test cases live in `tests/cases/<refactoring>/<group>/<case>/`, in the [format defined by the specification](https://github.com/RiktigRefactor/riktigrefactor.spec/blob/main/test-format.md): a `case.json`, an `input/` directory, and an `expected/` directory unless the case expects a refusal.
The program's entry point is `main.py` in `input/` and in `expected/`, and each must exit with status 0.
Programs run with `python -s -B main.py` in a temporary copy of the directory, so sibling modules can be imported; a case can list extra import roots, relative to the directory, in `"pythonPath"` (for example `["src"]`).

`case.json` fields: `options` (such as `{"newName": "count"}`), `refuse` (the expected refusal code), `naiveShouldFail`, `warnings`, `spec`, and `notes`.

Batch cases, under `tests/cases/batch/`, have no markers: their `actions.jsonl` holds one request per line, with locations in `input/`, and `refuse` is the code of the first refused action.
Their naive implementation runs each action alone and applies the union of the edits that do not overlap.

The selection is marked in the input with comments, which are removed before the refactoring runs:

```python
total = price * qty + shipping  # [price * qty]
total = x + x                    # [x]#2   (the second occurrence)
print(count)                     # |count  (a cursor at the start of "count")

# [
a = f(x)
b = g(a)
# ]
```

Run the tests with `RIKTIG_WRITE_EXPECTED=1` to write `expected/` for a new case, then read it and confirm it is correct before keeping it.
Edge cases must fail under the deliberately naive implementation of the refactoring in `tests/naive.py`.

### Citing the language specification

Python's specification is the [Language Reference](https://docs.python.org/3/reference/).
Following the [specification's citation table](https://github.com/RiktigRefactor/riktigrefactor.spec/blob/main/test-format.md#citations), every test case lists, in its `spec` field, sections of the Language Reference, written as `Python §<number> <title>` with the number and title as on the page for the latest Python version, for example `Python §4.2.2 Resolution of names`.
For a feature that has no section of its own, such as a PEP that the reference describes only in passing, write `Python feature: <name>`, for example `Python feature: PEP 695 type parameter scopes`.
The runner rejects any other form.
