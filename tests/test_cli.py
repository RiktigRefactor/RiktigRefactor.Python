import json

import pytest

from riktigrefactor import cli
from riktigrefactor.protocol import Position, Refused, Success, TextEdit


@pytest.fixture
def project(tmp_path):
    (tmp_path / "app.py").write_text("count = 1\nprint(count)\n", encoding="utf-8", newline="")
    return tmp_path


def fake_rename(edits):
    def rename(request, workspace):
        fake_rename.request = request
        return Success(workspace.root_text, tuple(edits))

    return rename


def test_a_refusal_has_exit_code_1(project, capsys):
    code = cli.main(["rename", "--workspace", str(project), "--file", "app.py", "--at", "1:9", "--new-name", "n"])
    assert code == cli.EXIT_REFUSED
    assert "no-symbol" in capsys.readouterr().err


def test_json_prints_the_protocol_result(project, capsys):
    code = cli.main(
        ["extract-iife", "--workspace", str(project), "--file", "app.py", "--range", "1:1-1:6", "--json"]
    )
    assert code == cli.EXIT_REFUSED
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "refused"
    assert printed["reasons"][0]["code"] == "expression-is-assignment-target"
    assert printed["workspaceRoot"] == str(project.resolve())


def test_extract_iife_previews_and_applies(tmp_path, capsys):
    (tmp_path / "app.py").write_text("def f(a, b):\n    return a + b\n", encoding="utf-8", newline="")
    arguments = ["extract-iife", "--workspace", str(tmp_path), "--file", "app.py", "--range", "2:12-2:17"]
    assert cli.main(arguments) == cli.EXIT_SUCCESS
    assert "+    return (lambda a, b: a + b)(a, b)\n" in capsys.readouterr().out
    assert cli.main([*arguments, "--apply"]) == cli.EXIT_SUCCESS
    assert (tmp_path / "app.py").read_text() == "def f(a, b):\n    return (lambda a, b: a + b)(a, b)\n"


def test_unknown_file_is_an_error_with_exit_code_2(project, capsys):
    code = cli.main(["rename", "--workspace", str(project), "--file", "nope.py", "--at", "1:1", "--new-name", "n"])
    assert code == cli.EXIT_ERROR
    assert "nope.py" in capsys.readouterr().err


def test_bad_position_is_an_error_with_exit_code_2(project, capsys):
    code = cli.main(["rename", "--workspace", str(project), "--file", "app.py", "--at", "one", "--new-name", "n"])
    assert code == cli.EXIT_ERROR


def test_preview_prints_a_diff_and_apply_writes(project, capsys, monkeypatch):
    edits = [
        TextEdit("app.py", Position(1, 1), Position(1, 6), "total"),
        TextEdit("app.py", Position(2, 7), Position(2, 12), "total"),
    ]
    monkeypatch.setattr(cli, "rename", fake_rename(edits))
    arguments = ["rename", "--workspace", str(project), "--file", "app.py", "--at", "1:1", "--new-name", "total"]
    assert cli.main(arguments) == cli.EXIT_SUCCESS
    assert "-count = 1\n-print(count)\n+total = 1\n+print(total)\n" in capsys.readouterr().out
    assert (project / "app.py").read_text() == "count = 1\nprint(count)\n"
    assert cli.main([*arguments, "--apply"]) == cli.EXIT_SUCCESS
    assert (project / "app.py").read_text() == "total = 1\nprint(total)\n"


def test_markers_in_the_file_select_instead_of_at(project, capsys, monkeypatch):
    (project / "app.py").write_text("count = 1\nprint(count)  # |count\n", encoding="utf-8", newline="")
    monkeypatch.setattr(cli, "rename", fake_rename([]))
    assert cli.main(["rename", "--workspace", str(project), "--new-name", "total"]) == cli.EXIT_SUCCESS
    assert fake_rename.request.file == "app.py"
    assert fake_rename.request.position == Position(2, 7)
    cli.main(["rename", "--workspace", str(project), "--new-name", "total", "--apply"])
    assert (project / "app.py").read_text() == "count = 1\nprint(count)\n"


def test_without_selection_or_markers_is_an_error(project):
    assert cli.main(["rename", "--workspace", str(project), "--new-name", "x"]) == cli.EXIT_ERROR


BATCH_PROGRAM = "def f(a, b):\n    return a - b\n"


def write_batch(tmp_path, *requests):
    (tmp_path / "app.py").write_text(BATCH_PROGRAM, encoding="utf-8", newline="")
    actions = tmp_path / "actions.jsonl"
    lines = []
    for column, new_name in requests:
        position = {"line": 1, "column": column}
        location = {"file": "app.py", "start": position, "end": position}
        lines.append(json.dumps({"refactoring": "rename", "location": location, "options": {"newName": new_name}}))
    actions.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ["batch", "--workspace", str(tmp_path), str(actions)]


def test_batch_previews_and_applies_a_swap(tmp_path, capsys):
    arguments = write_batch(tmp_path, (7, "b"), (10, "a"))
    assert cli.main(arguments) == cli.EXIT_SUCCESS
    assert "+def f(b, a):\n+    return b - a\n" in capsys.readouterr().out
    assert (tmp_path / "app.py").read_text() == BATCH_PROGRAM
    assert cli.main([*arguments, "--apply"]) == cli.EXIT_SUCCESS
    assert (tmp_path / "app.py").read_text() == "def f(b, a):\n    return b - a\n"


def test_atomic_batch_with_a_conflict_applies_nothing(tmp_path, capsys):
    arguments = write_batch(tmp_path, (7, "c"), (10, "c"))
    assert cli.main([*arguments, "--apply"]) == cli.EXIT_REFUSED
    assert "line 2 (conflicts with line 1): refused [batch-semantic-conflict]" in capsys.readouterr().err
    assert (tmp_path / "app.py").read_text() == BATCH_PROGRAM


def test_best_effort_batch_applies_the_actions_without_conflict(tmp_path):
    arguments = write_batch(tmp_path, (7, "c"), (10, "c"))
    assert cli.main([*arguments, "--best-effort", "--apply"]) == cli.EXIT_REFUSED
    assert (tmp_path / "app.py").read_text() == "def f(c, b):\n    return c - b\n"


def test_batch_json_prints_the_batch_result(tmp_path, capsys):
    arguments = write_batch(tmp_path, (7, "c"), (10, "c"))
    assert cli.main([*arguments, "--best-effort", "--json"]) == cli.EXIT_REFUSED
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "partial"
    assert [action["status"] for action in printed["results"]] == ["success", "refused"]


def test_batch_with_a_bad_line_or_missing_file_is_an_error(tmp_path, capsys):
    arguments = write_batch(tmp_path, (7, "c"))
    (tmp_path / "actions.jsonl").write_text("{oops\n", encoding="utf-8")
    assert cli.main(arguments) == cli.EXIT_ERROR
    assert "line 1" in capsys.readouterr().err
    assert cli.main([*arguments[:-1], str(tmp_path / "missing.jsonl")]) == cli.EXIT_ERROR
