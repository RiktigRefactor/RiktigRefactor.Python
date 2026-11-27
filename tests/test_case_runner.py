"""Tests of the case runner itself, using a small fake rename (the real refactorings come later)."""

import json
import re
from pathlib import Path

import pytest

import test_cases
from riktigrefactor.protocol import Success
from riktigrefactor.semantics import analyze_workspace


def fake_rename(request, workspace):
    bindings = analyze_workspace(workspace)
    offset = workspace.file(request.file).offset_of_position(request.position)
    target = bindings.occurrences_at_cursor(request.file, offset)[0]
    origin = bindings.origin_of(target.symbol)
    edits = [
        workspace.edit(o.file, o.start_offset, o.end_offset, request.new_name)
        for o in bindings.occurrences_with_origin(origin)
        if o.source_name == target.source_name
    ]
    return Success(workspace.root_text, tuple(edits))


def textual_rename(workspace, request):
    file = workspace.file(request.file)
    cursor = file.offset_of_position(request.position)
    old_name = re.match(r"\w+", file.text[cursor:]).group()
    return {
        path: re.sub(rf"\b{old_name}\b", request.new_name, source.text)
        for path, source in workspace.files.items()
    }


@pytest.fixture
def cases_root(tmp_path, monkeypatch):
    root = tmp_path / "cases"
    refactoring = test_cases.REFACTORINGS["rename"]
    fake = test_cases.RefactoringUnderTest(refactoring.make_request, fake_rename, textual_rename)
    monkeypatch.setattr(test_cases, "CASES_ROOT", root)
    monkeypatch.setattr(test_cases, "REFACTORINGS", {**test_cases.REFACTORINGS, "rename": fake})
    return root


def make_case(root: Path, name: str, program: str, metadata: dict, expected: str | None = None) -> Path:
    case = root / "rename" / "group" / name
    (case / "input").mkdir(parents=True)
    (case / "input" / "main.py").write_text(program, encoding="utf-8", newline="")
    metadata = {"options": {"newName": "amount"}, "spec": ["Python §4.2.2 Resolution of names"], **metadata}
    (case / "case.json").write_text(json.dumps(metadata), encoding="utf-8")
    if expected is not None:
        (case / "expected").mkdir()
        (case / "expected" / "main.py").write_text(expected, encoding="utf-8", newline="")
    return case


PROGRAM = "def f(count):  # |count\n    return count + 1\nassert f(1) == 2\n"
RENAMED = "def f(amount):\n    return amount + 1\nassert f(1) == 2\n"
SHADOWED_PROGRAM = (
    "count = 10\n"
    "def f(count):  # |count\n    return count + 1\n"
    "assert f(1) == 2\n"
    "assert globals()['co' + 'unt'] == 10\n"
)
SHADOWED_RENAMED = SHADOWED_PROGRAM.replace("def f(count):  # |count", "def f(amount):").replace(
    "return count + 1", "return amount + 1"
)


def test_success_case_passes_when_output_equals_expected(cases_root, tmp_path):
    case = make_case(cases_root, "ok", PROGRAM, {}, RENAMED)
    test_cases.test_case(case, tmp_path / "run")


def test_success_case_fails_when_output_differs_from_expected(cases_root, tmp_path):
    case = make_case(cases_root, "differs", PROGRAM, {}, RENAMED.replace("amount", "total"))
    with pytest.raises(AssertionError, match="differs from expected"):
        test_cases.test_case(case, tmp_path / "run")


def test_expected_directory_is_written_on_request(cases_root, tmp_path, monkeypatch):
    case = make_case(cases_root, "write", PROGRAM, {})
    monkeypatch.setattr(test_cases, "WRITE_EXPECTED", True)
    test_cases.test_case(case, tmp_path / "run")
    assert (case / "expected" / "main.py").read_text(encoding="utf-8") == RENAMED


def test_input_program_that_fails_is_a_bad_test(cases_root, tmp_path):
    case = make_case(cases_root, "bad", PROGRAM.replace("== 2", "== 3"), {}, RENAMED)
    with pytest.raises(AssertionError, match="input program fails"):
        test_cases.test_case(case, tmp_path / "run")


def test_naive_implementation_must_fail_the_edge_case(cases_root, tmp_path):
    case = make_case(cases_root, "edge", SHADOWED_PROGRAM, {"naiveShouldFail": True}, SHADOWED_RENAMED)
    test_cases.test_case(case, tmp_path / "run")


def test_naive_implementation_that_passes_is_reported(cases_root, tmp_path):
    case = make_case(cases_root, "weak", PROGRAM, {"naiveShouldFail": True}, RENAMED)
    with pytest.raises(AssertionError, match="naive implementation passes"):
        test_cases.test_case(case, tmp_path / "run")


def test_citations_must_name_the_language_reference(cases_root, tmp_path):
    case = make_case(cases_root, "citation", PROGRAM, {"spec": ["PEP 227"]}, RENAMED)
    with pytest.raises(AssertionError, match="is not 'Python"):
        test_cases.test_case(case, tmp_path / "run")


def test_refusal_case_checks_the_code(cases_root, tmp_path, monkeypatch):
    from riktigrefactor.protocol import Reason, Refused

    refusing = test_cases.RefactoringUnderTest(
        test_cases.REFACTORINGS["rename"].make_request,
        lambda request, workspace: Refused(workspace.root_text, (Reason("binding-would-change", "no"),)),
        textual_rename,
    )
    monkeypatch.setitem(test_cases.REFACTORINGS, "rename", refusing)
    case = make_case(cases_root, "refused", PROGRAM, {"refuse": "binding-would-change"})
    test_cases.test_case(case, tmp_path / "run")
    wrong = make_case(cases_root, "wrong-code", PROGRAM, {"refuse": "something-else"})
    with pytest.raises(AssertionError):
        test_cases.test_case(wrong, tmp_path / "run2")
