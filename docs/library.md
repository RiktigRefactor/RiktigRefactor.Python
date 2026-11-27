# Library

```python
from riktigrefactor import ExtractIifeRequest, Position, RenameRequest, Workspace
from riktigrefactor.extract_iife import extract_iife
from riktigrefactor.rename import rename

workspace = Workspace.load("path/to/project")
renamed = rename(RenameRequest("src/order.py", Position(12, 5), "count"), workspace)
extracted = extract_iife(ExtractIifeRequest("src/order.py", Position(12, 19), Position(12, 30)), workspace)
```

The package is not published yet.
The result follows the [protocol](https://github.com/RiktigRefactor/riktigrefactor.spec/blob/main/protocol.md): a `Success` with edits (1-based lines and columns), or a `Refused` with reason codes; `riktigrefactor.protocol.to_json` gives the JSON form.
The workspace is not modified; `Workspace.apply_edits(edits)` returns the new text of each changed file.

A batch runs several requests together (see [the command line](command-line.md#batch)):

```python
from riktigrefactor.batch import parse_actions, run_batch

actions = parse_actions(open("actions.jsonl", encoding="utf-8").read(), workspace)
result = run_batch(actions, workspace, best_effort=False)
new_texts = workspace.apply_edits(result.edits)
```

`result.status` is `success`, `partial`, or `refused`, `result.actions` has one result per action, and `result.to_json()` gives the JSON form.
