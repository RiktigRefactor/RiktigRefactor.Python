"""The `riktig-py` command line (see docs/command-line.md)."""

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from riktigrefactor import markers
from riktigrefactor.batch import BatchRequestError, BatchResult, BatchStatus, parse_actions, run_batch
from riktigrefactor.diff import unified_diff
from riktigrefactor.extract_iife import extract_iife
from riktigrefactor.protocol import (
    ExtractIifeRequest,
    Position,
    RefusalError,
    RenameRequest,
    Result,
    Success,
    to_json,
)
from riktigrefactor.rename import rename
from riktigrefactor.workspace import Workspace

EXIT_SUCCESS = 0
EXIT_REFUSED = 1
EXIT_ERROR = 2

_POSITION = re.compile(r"^(\d+):(\d+)$")
_RANGE = re.compile(r"^(\d+):(\d+)-(\d+):(\d+)$")


class UsageError(Exception):
    pass


def _parse_position(text: str) -> Position:
    match = _POSITION.match(text)
    if match is None:
        raise UsageError(f"{text!r} is not a position; write LINE:COLUMN, such as 12:5.")
    return Position(int(match.group(1)), int(match.group(2)))


def _parse_range(text: str) -> tuple[Position, Position]:
    match = _RANGE.match(text)
    if match is None:
        raise UsageError(f"{text!r} is not a range; write LINE:COLUMN-LINE:COLUMN, such as 12:5-14:20.")
    line1, column1, line2, column2 = (int(group) for group in match.groups())
    return Position(line1, column1), Position(line2, column2)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="riktig-py", description="Seriously safe refactorings for Python.")
    commands = parser.add_subparsers(dest="command", required=True)

    def add_common_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--workspace", default=".", help="the project root directory (default: the current directory)")
        command.add_argument("--file", help="the file to refactor; optional when exactly one file has selection markers")
        command.add_argument("--apply", action="store_true", help="write the changes to disk instead of printing a diff")
        command.add_argument("--json", action="store_true", help="print the protocol result as JSON instead of a diff")

    rename_command = commands.add_parser("rename", help="rename a symbol and its references")
    add_common_arguments(rename_command)
    rename_command.add_argument("--at", help="the cursor, LINE:COLUMN; omit it to use a marker in the file")
    rename_command.add_argument("--new-name", required=True)

    extract_command = commands.add_parser("extract-iife", help="wrap a selection in an immediately-invoked function")
    add_common_arguments(extract_command)
    extract_command.add_argument("--range", help="the selection, LINE:COLUMN-LINE:COLUMN; omit it to use markers in the file")

    batch_command = commands.add_parser("batch", help="run several refactorings together, from a JSON Lines file")
    batch_command.add_argument("--workspace", default=".", help="the project root directory (default: the current directory)")
    batch_command.add_argument("actions", help="the JSON Lines file of requests, with locations in the original files")
    mode = batch_command.add_mutually_exclusive_group()
    mode.add_argument("--atomic", action="store_true", help="apply nothing if any action is refused (the default)")
    mode.add_argument("--best-effort", action="store_true", help="apply the actions that succeed without conflict")
    batch_command.add_argument("--apply", action="store_true", help="write the changes to disk instead of printing a diff")
    batch_command.add_argument("--json", action="store_true", help="print the batch result as JSON instead of a diff")
    return parser


def _marked_selection(workspace: Workspace, file: str | None) -> tuple[Workspace, str, markers.Selection]:
    candidates = [workspace.file(file).path] if file else list(workspace.files)
    found = []
    for path in candidates:
        stripped, selection = markers.strip_markers(workspace.files[path].text)
        if selection is not None:
            found.append((path, stripped, selection))
    if len(found) != 1:
        raise UsageError("Give --at or --range, or mark the selection in exactly one file.")
    path, stripped, selection = found[0]
    return workspace.with_texts({path: stripped}), path, selection


def _run(arguments: argparse.Namespace) -> tuple[Workspace, Workspace, Result]:
    original = Workspace.load(arguments.workspace)
    workspace = original
    if arguments.command == "rename":
        explicit = _parse_position(arguments.at) if arguments.at else None
        selection_start = selection_end = explicit
    else:
        explicit_range = _parse_range(arguments.range) if arguments.range else None
        selection_start, selection_end = explicit_range if explicit_range else (None, None)
    if selection_start is None or selection_end is None:
        workspace, file, selection = _marked_selection(original, arguments.file)
        selection_start, selection_end = selection.start, selection.end
    else:
        if not arguments.file:
            raise UsageError("--file is required with --at or --range.")
        file = original.file(arguments.file).path
    if arguments.command == "rename":
        request = RenameRequest(file, selection_start, arguments.new_name)
        result = rename(request, workspace)
    else:
        extract_request = ExtractIifeRequest(file, selection_start, selection_end)
        result = extract_iife(extract_request, workspace)
    return original, workspace, result


def _describe_refusal(result: Result) -> str:
    lines = []
    for reason in result.reasons:  # type: ignore[union-attr]
        where = ""
        if reason.location is not None:
            where = f" ({reason.location.file}:{reason.location.start.line}:{reason.location.start.column})"
        lines.append(f"refused [{reason.code}]{where}: {reason.message}")
        if reason.suggestion:
            lines.append(f"  suggestion: {reason.suggestion}")
    return "\n".join(lines)


def _describe_batch_refusals(result: BatchResult) -> str:
    lines = []
    for action in result.actions:
        if isinstance(action.result, Success):
            continue
        conflicts = ""
        if action.conflicts_with:
            conflicts = f" (conflicts with line {', '.join(str(line) for line in action.conflicts_with)})"
        for description in _describe_refusal(action.result).split("\n"):
            lines.append(f"line {action.line}{conflicts}: {description}")
    return "\n".join(lines)


def _main_batch(arguments: argparse.Namespace) -> int:
    try:
        workspace = Workspace.load(arguments.workspace)
        actions_text = Path(arguments.actions).read_text(encoding="utf-8")
        actions = parse_actions(actions_text, workspace)
        result = run_batch(actions, workspace, best_effort=arguments.best_effort)
    except (OSError, BatchRequestError, RefusalError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
    if arguments.json:
        print(json.dumps(result.to_json(), indent=2, ensure_ascii=False))
    else:
        refusals = _describe_batch_refusals(result)
        if refusals:
            print(refusals, file=sys.stderr)
    new_texts = workspace.apply_edits(result.edits)
    if arguments.apply:
        workspace.write_texts(new_texts)
        if not arguments.json and new_texts:
            print(f"applied changes to {len(new_texts)} file(s)")
    elif not arguments.json:
        original_texts = {path: workspace.files[path].text for path in new_texts}
        sys.stdout.write(unified_diff(original_texts, new_texts))
        for warning in result.warnings:
            print(f"warning [{warning.code}]: {warning.message}", file=sys.stderr)
    if result.status == BatchStatus.SUCCESS:
        return EXIT_SUCCESS
    return EXIT_REFUSED


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    if arguments.command == "batch":
        return _main_batch(arguments)
    try:
        original, workspace, result = _run(arguments)
    except (UsageError, RefusalError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
    except markers.MarkerError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
    if arguments.json:
        print(json.dumps(to_json(result), indent=2, ensure_ascii=False))
    if not isinstance(result, Success):
        if not arguments.json:
            print(_describe_refusal(result), file=sys.stderr)
        return EXIT_REFUSED
    new_texts = {path: file.text for path, file in workspace.files.items() if file.text != original.files[path].text}
    new_texts.update(workspace.apply_edits(result.edits))
    original_texts = {path: original.files[path].text for path in new_texts}
    if arguments.apply:
        workspace.write_texts(new_texts)
        if not arguments.json:
            print(f"applied changes to {len(new_texts)} file(s)")
    elif not arguments.json:
        sys.stdout.write(unified_diff(original_texts, new_texts))
        for warning in result.warnings:
            print(f"warning [{warning.code}]: {warning.message}", file=sys.stderr)
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
