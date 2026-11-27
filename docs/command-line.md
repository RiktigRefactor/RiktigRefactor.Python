# Command line

The package is not published yet; from a clone, run `./build-and-test` once, then use `.venv/bin/riktig-py` (`.venv/Scripts/riktig-py` on Windows) or `python -m riktigrefactor` in place of `riktig-py`.

The commands are `rename`, `extract-iife`, and `batch`; each refactoring's page shows an example.

```shell
riktig-py rename --workspace . --file src/order.py --at 12:5 --new-name count
riktig-py extract-iife --workspace . --file src/order.py --range 12:5-14:20
riktig-py batch --workspace . actions.jsonl [--best-effort]
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

## Batch

`batch` runs several refactorings together, following the specification's [batch mode](https://github.com/RiktigRefactor/riktigrefactor.spec/blob/main/protocol.md#batch-mode).
The file holds JSON Lines: one [protocol](https://github.com/RiktigRefactor/riktigrefactor.spec/blob/main/protocol.md) request per line, such as:

```json
{"refactoring": "rename", "location": {"file": "src/order.py", "start": {"line": 12, "column": 5}, "end": {"line": 12, "column": 5}}, "options": {"newName": "count"}}
{"refactoring": "extract-iife", "location": {"file": "src/order.py", "start": {"line": 14, "column": 12}, "end": {"line": 14, "column": 30}}, "options": {}}
```

Every location refers to the files as they are before the batch, whatever the other actions change.
A request may leave out `workspace`; if it has one, it must be the batch's workspace.
Blank lines are skipped, and selection markers are not used.

- By default the batch is atomic (`--atomic`): if any action is refused or conflicts with another, nothing is applied.
- `--best-effort` applies the actions that succeed without conflict, and reports the rest.
- `--apply` and `--json` work as for the other commands.

When two actions conflict, the later one in the file is refused, with the code `batch-edits-overlap` or `batch-semantic-conflict`, and names the lines it conflicts with.
Renames are checked together, so a swap (`a→b` with `b→a`) or a rotation is accepted, and `a→c` with `b→c` in one scope is refused.
An Extract IIFE whose selection contains a renamed name uses the new name.

The JSON result has an overall `status` (`success`, `partial` when `--best-effort` applies only some actions, or `refused` when nothing is applied), the `edits` to apply, relative to the original files, and `results`: one result per action, in order.
Each result has the action's `line` in the file, its `refactoring`, and the protocol result: its own share of the edits, or its `reasons`, plus `conflictsWith` (the lines of the actions it conflicts with) for a conflict.
In an atomic batch that is refused, the actions that would succeed still show their edits, but the overall `edits` are empty.

The exit code is 0 when every action succeeds, 1 when any action is refused (even when `--best-effort` applied the others), and 2 when a line is not a request or the workspace cannot be loaded.
