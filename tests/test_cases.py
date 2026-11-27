"""Runs the test cases under tests/cases (the specification's test-format.md).

For each case: (1) the input program passes; (2) the refactoring gives the expected outcome;
(3) its output equals expected/ exactly; (4) the output program passes.
Cases under tests/cases/batch have no markers: their actions.jsonl holds the requests, with locations in input/.
`RIKTIG_WRITE_EXPECTED=1` writes expected/ from the actual output; review it before keeping it.
"""

import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from naive import naive_batch, naive_extract_iife, naive_rename
from program_runner import run_program
from riktigrefactor import markers
from riktigrefactor.batch import BatchStatus, parse_actions, run_batch
from riktigrefactor.extract_iife import extract_iife
from riktigrefactor.protocol import ExtractIifeRequest, Refused, RenameRequest, Result, Success
from riktigrefactor.rename import rename
from riktigrefactor.workspace import Workspace

CASES_ROOT = Path(__file__).parent / "cases"
WRITE_EXPECTED = os.environ.get("RIKTIG_WRITE_EXPECTED") == "1"
CITATION = re.compile(r"^Python (§\d+(\.\d+)* \S.*|feature: \S.*)$")


@dataclass(frozen=True)
class RefactoringUnderTest:
    make_request: Callable[[str, markers.Selection, dict[str, Any]], Any]
    run: Callable[[Any, Workspace], Result]
    naive: Callable[[Workspace, Any], dict[str, str]]


REFACTORINGS = {
    "rename": RefactoringUnderTest(
        lambda file, selection, options: RenameRequest(file, selection.start, options["newName"]),
        rename,
        naive_rename,
    ),
    "extract-iife": RefactoringUnderTest(
        lambda file, selection, options: ExtractIifeRequest(file, selection.start, selection.end),
        extract_iife,
        naive_extract_iife,
    ),
}


def discover_cases() -> list[Path]:
    if not CASES_ROOT.exists():
        return []
    return sorted(path.parent for path in CASES_ROOT.rglob("case.json"))


def case_id(case_directory: Path) -> str:
    return case_directory.relative_to(CASES_ROOT).as_posix()


def read_tree(directory: Path) -> dict[str, str]:
    files = {}
    if directory.is_dir():
        for path in sorted(directory.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                files[path.relative_to(directory).as_posix()] = path.read_bytes().decode("utf-8")
    return files


def write_tree(directory: Path, files: dict[str, str]) -> None:
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    for relative, text in files.items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))


def strip_markers_from_files(files: dict[str, str]) -> tuple[dict[str, str], str, markers.Selection]:
    stripped_files = {}
    found: list[tuple[str, markers.Selection]] = []
    for path, text in files.items():
        if path.endswith(".py"):
            text, selection = markers.strip_markers(text)
            if selection is not None:
                found.append((path, selection))
        stripped_files[path] = text
    assert len(found) == 1, f"the input needs exactly one selection marker, found {len(found)}"
    return stripped_files, found[0][0], found[0][1]


BATCH = "batch"


def check_metadata(metadata: dict[str, Any], case_directory: Path) -> None:
    refactoring = case_directory.relative_to(CASES_ROOT).parts[0]
    assert refactoring in REFACTORINGS or refactoring == BATCH, f"unknown refactoring directory {refactoring}"
    if refactoring == BATCH:
        assert (case_directory / "actions.jsonl").is_file(), "a batch case has an actions.jsonl"
    assert metadata.get("spec"), "case.json needs a non-empty spec list of language reference citations"
    for citation in metadata["spec"]:
        assert CITATION.match(citation), f"{citation!r} is not 'Python §<number> <title>' or 'Python feature: <name>'"
    assert (case_directory / "input").is_dir(), "the case has no input/ directory"
    if "refuse" in metadata:
        assert not (case_directory / "expected").exists(), "a refusal case has no expected/ directory"


@pytest.mark.parametrize("case_directory", discover_cases(), ids=case_id)
def test_case(case_directory: Path, tmp_path: Path) -> None:
    metadata = json.loads((case_directory / "case.json").read_text(encoding="utf-8"))
    check_metadata(metadata, case_directory)
    python_path = metadata.get("pythonPath", [])

    input_files = read_tree(case_directory / "input")
    input_directory = tmp_path / "input"
    write_tree(input_directory, {path: text for path, text in input_files.items()})
    input_outcome = run_program(input_directory, python_path)
    assert input_outcome.passed, f"the input program fails (a bad test):\n{input_outcome.output}"

    if case_directory.relative_to(CASES_ROOT).parts[0] == BATCH:
        run_batch_case(case_directory, metadata, input_files, input_directory, tmp_path)
        return
    refactoring = REFACTORINGS[case_directory.relative_to(CASES_ROOT).parts[0]]
    unmarked_files, selection_file, selection = strip_markers_from_files(input_files)
    workspace = Workspace.from_texts(
        input_directory, {path: text for path, text in unmarked_files.items() if path.endswith(".py")}
    )
    request = refactoring.make_request(selection_file, selection, metadata.get("options", {}))
    result = refactoring.run(request, workspace)

    if "refuse" in metadata:
        assert isinstance(result, Refused), f"expected the refusal {metadata['refuse']}, got {result}"
        assert result.reasons[0].code == metadata["refuse"], f"got {result.reasons}"
        actual_files = unmarked_files
    else:
        assert isinstance(result, Success), f"expected success, got {result}"
        actual_files = {**unmarked_files, **workspace.apply_edits(result.edits)}
        reported = {warning.code for warning in result.warnings}
        assert set(metadata.get("warnings", [])) <= reported, f"expected warnings {metadata.get('warnings')}, got {reported}"
        if WRITE_EXPECTED:
            write_tree(case_directory / "expected", actual_files)
        expected_files = read_tree(case_directory / "expected")
        assert actual_files == expected_files, "the output differs from expected/"
        output_directory = tmp_path / "output"
        write_tree(output_directory, actual_files)
        output_outcome = run_program(output_directory, python_path)
        assert output_outcome.passed, f"the refactored program fails (a correctness bug):\n{output_outcome.output}"

    if metadata.get("naiveShouldFail"):
        naive_texts = refactoring.naive(workspace, request)
        naive_directory = tmp_path / "naive"
        write_tree(naive_directory, {**unmarked_files, **naive_texts})
        naive_outcome = run_program(naive_directory, python_path)
        assert not naive_outcome.passed, "the naive implementation passes this case, so its assertions cannot fail"


def run_batch_case(
    case_directory: Path, metadata: dict[str, Any], input_files: dict[str, str], input_directory: Path, tmp_path: Path
) -> None:
    python_path = metadata.get("pythonPath", [])
    workspace = Workspace.from_texts(input_directory, {path: text for path, text in input_files.items() if path.endswith(".py")})
    actions = parse_actions((case_directory / "actions.jsonl").read_text(encoding="utf-8"), workspace)
    result = run_batch(actions, workspace)

    if "refuse" in metadata:
        assert result.status == BatchStatus.REFUSED, f"expected the refusal {metadata['refuse']}, got {result}"
        refused = [action.result for action in result.actions if isinstance(action.result, Refused)]
        assert refused[0].reasons[0].code == metadata["refuse"], f"got {refused}"
        assert result.edits == ()
    else:
        assert result.status == BatchStatus.SUCCESS, f"expected success, got {result}"
        actual_files = {**input_files, **workspace.apply_edits(result.edits)}
        if WRITE_EXPECTED:
            write_tree(case_directory / "expected", actual_files)
        expected_files = read_tree(case_directory / "expected")
        assert actual_files == expected_files, "the output differs from expected/"
        output_directory = tmp_path / "output"
        write_tree(output_directory, actual_files)
        output_outcome = run_program(output_directory, python_path)
        assert output_outcome.passed, f"the refactored program fails (a correctness bug):\n{output_outcome.output}"

    if metadata.get("naiveShouldFail"):
        naive_directory = tmp_path / "naive"
        write_tree(naive_directory, {**input_files, **naive_batch(workspace, actions)})
        naive_outcome = run_program(naive_directory, python_path)
        assert not naive_outcome.passed, "the naive implementation passes this case, so its assertions cannot fail"
