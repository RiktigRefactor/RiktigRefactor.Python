import json

from riktigrefactor.diff import unified_diff
from riktigrefactor.protocol import (
    Location,
    Position,
    Reason,
    RefusalError,
    Refused,
    RefactoringWarning,
    RenameRequest,
    Success,
    TextEdit,
    returning_refusals,
    to_json,
)
from riktigrefactor.workspace import Workspace


def test_success_serializes_to_the_protocol_shape():
    edit = TextEdit("src/a.py", Position(1, 5), Position(1, 8), "count")
    warning = RefactoringWarning("trivia-moved", "moved", Location("src/a.py", Position(1, 1), Position(1, 2)))
    result = Success("/work", (edit,), (warning,))
    assert to_json(result) == {
        "status": "success",
        "workspaceRoot": "/work",
        "edits": [
            {
                "file": "src/a.py",
                "start": {"line": 1, "column": 5},
                "end": {"line": 1, "column": 8},
                "newText": "count",
            }
        ],
        "warnings": [
            {
                "code": "trivia-moved",
                "message": "moved",
                "location": {"file": "src/a.py", "start": {"line": 1, "column": 1}, "end": {"line": 1, "column": 2}},
            }
        ],
    }
    json.dumps(to_json(result))


def test_refusal_serializes_with_optional_fields_only_when_present():
    reason = Reason("no-symbol", "Nothing here.")
    assert to_json(Refused("/work", (reason,))) == {
        "status": "refused",
        "workspaceRoot": "/work",
        "reasons": [{"code": "no-symbol", "message": "Nothing here."}],
    }
    full = Reason("x", "m", Location("a.py", Position(1, 1), Position(1, 1)), "do this")
    assert to_json(Refused("/w", (full,)))["reasons"][0]["suggestion"] == "do this"


def test_request_serializes_to_the_protocol_shape():
    request = RenameRequest("a.py", Position(2, 3), "count")
    assert request.to_json("/ws") == {
        "refactoring": "rename",
        "workspace": "/ws",
        "location": {"file": "a.py", "start": {"line": 2, "column": 3}, "end": {"line": 2, "column": 3}},
        "options": {"newName": "count"},
    }


def test_returning_refusals_converts_the_exception_to_a_refused_result():
    @returning_refusals
    def refactoring(request, workspace):
        raise RefusalError("no-symbol", "Nothing here.", suggestion="Move the cursor.")

    workspace = Workspace.from_texts("/ws", {})
    result = refactoring(None, workspace)
    assert isinstance(result, Refused)
    assert result.reasons[0].code == "no-symbol"
    assert result.reasons[0].suggestion == "Move the cursor."


def test_unified_diff_shows_changed_files_only():
    diff = unified_diff({"a.py": "x = 1\ny = 2\n", "b.py": "same\n"}, {"a.py": "x = 1\ny = 3\n", "b.py": "same\n"})
    assert diff == "--- a/a.py\n+++ b/a.py\n" + "@" * 2 + " -1,2 +1,2 " + "@" * 2 + "\n x = 1\n-y = 2\n+y = 3\n"


def test_unified_diff_marks_a_missing_final_newline():
    diff = unified_diff({"a.py": "x = 1"}, {"a.py": "x = 2"})
    assert diff.endswith("-x = 1\n\\ No newline at end of file\n+x = 2\n\\ No newline at end of file\n")
