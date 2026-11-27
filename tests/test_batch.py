import itertools
import json

import pytest

import riktigrefactor.batch as batch
from riktigrefactor.batch import BatchRequestError, BatchStatus, parse_actions, run_batch
from riktigrefactor.protocol import Reason, Refused, Success
from riktigrefactor.workspace import Workspace

PROGRAM = (
    "def f(a, b):\n"
    "    return a - b\n"
    "\n"
    "\n"
    "def g(x, y):\n"
    "    return x * y\n"
)


def rename(line, column, new_name, file="main.py"):
    position = {"line": line, "column": column}
    return {"refactoring": "rename", "location": {"file": file, "start": position, "end": position}, "options": {"newName": new_name}}


def extract(start, end, file="main.py"):
    location = {"file": file, "start": {"line": start[0], "column": start[1]}, "end": {"line": end[0], "column": end[1]}}
    return {"refactoring": "extract-iife", "location": location, "options": {}}


def run(requests, text=PROGRAM, best_effort=False):
    workspace = Workspace.from_texts("/project", {"main.py": text})
    actions = parse_actions("\n".join(json.dumps(request) for request in requests))
    return workspace, run_batch(actions, workspace, best_effort=best_effort)


def new_text(workspace, result):
    return workspace.apply_edits(result.edits).get("main.py", workspace.files["main.py"].text)


def codes(result):
    return [
        action.result.reasons[0].code if isinstance(action.result, Refused) else "success" for action in result.actions
    ]


def test_renames_to_one_name_in_different_scopes_do_not_conflict():
    workspace, result = run([rename(1, 7, "n"), rename(5, 7, "n")])
    assert result.status == BatchStatus.SUCCESS
    assert new_text(workspace, result) == PROGRAM.replace("a", "n", 1).replace("return a", "return n").replace("x", "n")


def test_renames_to_one_name_in_one_scope_conflict_and_name_the_other_line():
    workspace, result = run([rename(1, 7, "c"), rename(1, 10, "c")], best_effort=True)
    assert codes(result) == ["success", "batch-semantic-conflict"]
    assert result.actions[1].conflicts_with == (1,)
    assert result.status == BatchStatus.PARTIAL
    assert new_text(workspace, result) == PROGRAM.replace("(a, b)", "(c, b)").replace("a - b", "c - b")


def test_atomic_batch_with_a_conflict_has_no_edits_but_reports_each_action():
    workspace, result = run([rename(1, 7, "c"), rename(1, 10, "c")])
    assert result.status == BatchStatus.REFUSED
    assert result.edits == ()
    assert isinstance(result.actions[0].result, Success)
    assert result.actions[0].result.edits


def test_a_lone_rename_that_collides_keeps_its_own_refusal():
    workspace, result = run([rename(1, 7, "b")])
    assert codes(result) == ["binding-would-change"]


def test_a_swap_with_an_unrelated_collision_still_succeeds():
    workspace, result = run([rename(1, 7, "b"), rename(1, 10, "a"), rename(5, 7, "y")], best_effort=True)
    assert codes(result) == ["success", "success", "binding-would-change"]
    assert "def f(b, a):\n    return b - a\n" in new_text(workspace, result)


def test_an_action_refused_alone_keeps_its_own_code():
    workspace, result = run([rename(3, 1, "z"), extract((2, 12), (2, 17))], best_effort=True)
    assert codes(result) == ["no-symbol", "success"]


def test_overlapping_actions_refuse_the_later_one():
    workspace, result = run([rename(1, 7, "p"), rename(2, 12, "q")])
    assert codes(result) == ["success", "batch-edits-overlap"]
    assert result.actions[1].conflicts_with == (1,)


def test_a_rename_inside_an_extraction_is_used_by_it():
    workspace, result = run([rename(1, 7, "first"), extract((2, 12), (2, 17))])
    assert result.status == BatchStatus.SUCCESS
    assert "    return (lambda first, b: first - b)(first, b)\n" in new_text(workspace, result)
    rename_result, extract_result = (action.result for action in result.actions)
    assert all(edit.start.line == 1 for edit in rename_result.edits)
    assert len(extract_result.edits) == 1


def test_actions_without_interactions_give_the_same_result_in_any_order():
    requests = [rename(1, 7, "first"), extract((2, 12), (2, 17)), extract((6, 12), (6, 17)), rename(5, 10, "z")]
    results = set()
    for permutation in itertools.permutations(requests):
        workspace, result = run(list(permutation))
        assert result.status == BatchStatus.SUCCESS
        results.add(new_text(workspace, result))
    assert len(results) == 1


def test_an_extraction_that_refuses_after_the_other_edits_conflicts_with_them(monkeypatch):
    original_extract_iife = batch.extract_iife

    def refuses_after_edits(request, workspace):
        if "first" in workspace.files["main.py"].text:
            return Refused(workspace.root_text, (Reason("possibly-unbound-variable", "no"),))
        return original_extract_iife(request, workspace)

    monkeypatch.setattr(batch, "extract_iife", refuses_after_edits)
    workspace, result = run([rename(1, 7, "first"), extract((2, 12), (2, 17))], best_effort=True)
    assert codes(result) == ["success", "batch-semantic-conflict"]
    assert result.actions[1].conflicts_with == (1,)
    assert "possibly-unbound-variable" in result.actions[1].result.reasons[0].message


def test_an_unknown_refactoring_is_not_implemented():
    workspace, result = run([{"refactoring": "move-static-member", "location": {}}])
    assert codes(result) == ["not-implemented"]


def test_json_has_one_result_per_line_with_its_line_number():
    workspace = Workspace.from_texts("/project", {"main.py": PROGRAM})
    text = json.dumps(rename(1, 7, "c")) + "\n\n" + json.dumps(rename(1, 10, "c")) + "\n"
    printed = run_batch(parse_actions(text), workspace).to_json()
    assert printed["status"] == "refused"
    assert printed["edits"] == []
    assert [action["line"] for action in printed["results"]] == [1, 3]
    assert printed["results"][1]["conflictsWith"] == [1]
    assert printed["results"][1]["reasons"][0]["code"] == "batch-semantic-conflict"
    assert "workspaceRoot" not in printed["results"][0]


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        "[1]",
        '{"refactoring": "rename", "location": {"file": "main.py", "start": {"line": 1, "column": 7}}}',
        '{"refactoring": "extract-iife", "location": {"start": {"line": 1, "column": 7}}}',
        '{"refactoring": "rename", "location": {"file": "main.py", "start": {"line": "1", "column": 7}}, '
        '"options": {"newName": "n"}}',
    ],
)
def test_a_line_that_is_not_a_request_is_an_error(line):
    with pytest.raises(BatchRequestError, match="line 1"):
        parse_actions(line)


def test_a_request_for_another_workspace_is_an_error(tmp_path):
    workspace = Workspace.from_texts(tmp_path, {"main.py": PROGRAM})
    request = {**rename(1, 7, "n"), "workspace": str(tmp_path / "elsewhere")}
    with pytest.raises(BatchRequestError, match="workspace"):
        parse_actions(json.dumps(request), workspace)
    same = {**rename(1, 7, "n"), "workspace": str(tmp_path)}
    assert len(parse_actions(json.dumps(same), workspace)) == 1
