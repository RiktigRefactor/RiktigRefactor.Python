# Command line

The package is not published yet; from a clone, run `./build-and-test` once, then use `.venv/bin/riktig-py` (`.venv/Scripts/riktig-py` on Windows) or `python -m riktigrefactor` in place of `riktig-py`.

The commands are `rename` and `extract-iife`; each refactoring's page shows an example.

```shell
riktig-py rename --workspace . --file src/order.py --at 12:5 --new-name count
riktig-py extract-iife --workspace . --file src/order.py --range 12:5-14:20
```

The workspace is a project root directory (the default is the current directory): every `*.py` file under it, except in virtual environments and in hidden, `__pycache__`, `build`, and `dist` directories.
Module names come from the paths: a `src` directory at the root is an import root, like the root itself.

Positions are 1-based, and columns count Unicode scalar values.
Instead of `--at` or `--range`, the file can hold the [selection markers](building-and-testing.md#test-cases); then `--file` may be left out when exactly one file has markers.
The markers are removed from the file when the changes are previewed or applied.

- By default the command previews the changes as a unified diff.
- `--apply` writes the changes to disk.
- `--json` prints the result using the shared protocol, without the diff.

The exit code is 0 on success, 1 when the refactoring is refused, and 2 on an error such as an unknown file or a file that does not parse.
Each refusal has a code, listed in [refusal codes](../refusal-codes.md); see also [refusals and limitations](limitations.md).
