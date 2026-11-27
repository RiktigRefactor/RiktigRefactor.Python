"""Batch mode: several refactorings applied together (the specification's protocol.md, "Batch mode").

Every action's location refers to the original files (snapshot semantics), and the tool maps it through the edits of
the other actions. The steps:
  1. Each action runs alone on the snapshot; an action that refuses there is refused with its own reasons.
  2. Textual overlap: an action whose edits overlap an earlier action's edits is refused. A rename's edits inside the
     text that an Extract IIFE replaces are not an overlap: the extraction then uses the new names.
  3. The renames are verified together with one re-binding check, which accepts swaps (`a->b` with `b->a`) and
     refuses merges (`a->c` with `b->c` in one scope). A rename that is refused alone only because of what its new
     name would collide with is accepted when the renames it is linked to by name make the combination check pass.
  4. Each extraction, in file and position order, runs again on the result of all the edits accepted so far, at its
     mapped location, with all its checks and its own verification; one that refuses there conflicts with them.
When two actions conflict, the later one in the input is refused, and its reasons name the lines it conflicts with.
"""

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from riktigrefactor.extract_iife import extract_iife
from riktigrefactor.protocol import (
    ExtractIifeRequest,
    Location,
    Position,
    Reason,
    RefactoringWarning,
    Refused,
    RefusalCodes,
    RefusalError,
    RenameRequest,
    Result,
    Success,
    TextEdit,
)
from riktigrefactor.rename import RenamePlan, RenameRefusalCodes, plan_rename, verify_rename_plan
from riktigrefactor.semantics import Symbol
from riktigrefactor.verification import verify_edits
from riktigrefactor.workspace import EditSpan, Workspace, apply_spans


class BatchRefusalCodes:
    """The refusal codes of batch mode (see refusal-codes.md)."""

    EDITS_OVERLAP = "batch-edits-overlap"
    SEMANTIC_CONFLICT = "batch-semantic-conflict"


class BatchStatus:
    SUCCESS = "success"
    PARTIAL = "partial"
    REFUSED = "refused"


class BatchRequestError(Exception):
    """A line of the batch is not a request: the batch cannot be run at all."""


@dataclass(frozen=True)
class BatchAction:
    line: int
    """The 1-based line of the action in the JSON Lines input."""
    refactoring: str
    request: RenameRequest | ExtractIifeRequest | None
    """None for a refactoring that this tool does not implement."""


@dataclass(frozen=True)
class ActionResult:
    line: int
    refactoring: str
    result: Result
    conflicts_with: tuple[int, ...] = ()
    """The lines of the actions that this refused action conflicts with."""

    def to_json(self) -> dict[str, Any]:
        result = {"line": self.line, "refactoring": self.refactoring, **self.result.to_json()}
        del result["workspaceRoot"]
        if self.conflicts_with:
            result["conflictsWith"] = list(self.conflicts_with)
        return result


@dataclass(frozen=True)
class BatchResult:
    workspace_root: str
    status: str
    """`success` when every action applies; `refused` when nothing applies; `partial` in best-effort mode when some do."""
    edits: tuple[TextEdit, ...]
    """The edits to apply, relative to the snapshot; empty unless at least one action applies."""
    warnings: tuple[RefactoringWarning, ...]
    actions: tuple[ActionResult, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "workspaceRoot": self.workspace_root,
            "edits": [edit.to_json() for edit in self.edits],
            "warnings": [warning.to_json() for warning in self.warnings],
            "results": [action.to_json() for action in self.actions],
        }


# --------------------------------------------------------------------------------------------------------------------
# Reading the actions
# --------------------------------------------------------------------------------------------------------------------


def parse_actions(text: str, workspace: Workspace | None = None) -> list[BatchAction]:
    """Reads JSON Lines of protocol requests; blank lines are skipped. A request's `workspace`, if given, must be `workspace`."""
    actions = []
    for line_number, line in enumerate(text.split("\n"), start=1):
        if line.strip() == "":
            continue
        try:
            request_json = json.loads(line)
        except json.JSONDecodeError as error:
            raise BatchRequestError(f"line {line_number}: not JSON: {error}") from error
        actions.append(_action_from_json(line_number, request_json, workspace))
    return actions


def _action_from_json(line: int, request_json: Any, workspace: Workspace | None) -> BatchAction:
    def fail(message: str) -> BatchRequestError:
        return BatchRequestError(f"line {line}: {message}")

    if not isinstance(request_json, dict):
        raise fail("a request is a JSON object.")
    refactoring = request_json.get("refactoring")
    if not isinstance(refactoring, str):
        raise fail("the request has no \"refactoring\".")
    named_workspace = request_json.get("workspace")
    if named_workspace is not None and workspace is not None:
        if not isinstance(named_workspace, str) or Path(named_workspace).resolve() != workspace.root.resolve():
            raise fail(f"the request's workspace {named_workspace!r} is not the batch's workspace {workspace.root_text}.")
    if refactoring not in ("rename", "extract-iife"):
        return BatchAction(line, refactoring, None)
    location = request_json.get("location")
    if not isinstance(location, dict) or not isinstance(location.get("file"), str):
        raise fail("the request has no \"location\" with a \"file\".")
    start = _position_from_json(location.get("start"), fail)
    end = start
    if location.get("end") is not None:
        end = _position_from_json(location.get("end"), fail)
    options = request_json.get("options") or {}
    if not isinstance(options, dict):
        raise fail("\"options\" is not an object.")
    if refactoring == "rename":
        new_name = options.get("newName")
        if not isinstance(new_name, str):
            raise fail("a rename needs the option \"newName\".")
        return BatchAction(line, refactoring, RenameRequest(location["file"], start, new_name))
    return BatchAction(line, refactoring, ExtractIifeRequest(location["file"], start, end))


def _position_from_json(position_json: Any, fail) -> Position:
    if not isinstance(position_json, dict):
        raise fail("a position is an object with \"line\" and \"column\".")
    line, column = position_json.get("line"), position_json.get("column")
    if type(line) is not int or type(column) is not int:
        raise fail("a position's \"line\" and \"column\" are integers.")
    return Position(line, column)


# --------------------------------------------------------------------------------------------------------------------
# Running the batch
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Span:
    file: str
    start: int
    end: int

    def intersects(self, other: "_Span") -> bool:
        return self.file == other.file and self.start < other.end and other.start < self.end

    def contains(self, other: "_Span") -> bool:
        return self.file == other.file and self.start <= other.start and other.end <= self.end

    def strictly_contains_offset(self, file: str, offset: int) -> bool:
        return self.file == file and self.start < offset < self.end


@dataclass
class _Extraction:
    selection_start: int
    selection_end: int
    region: _Span
    """The text that the extraction replaces in the snapshot."""
    warnings: tuple[RefactoringWarning, ...] = ()


@dataclass
class _AppliedSpan:
    span: EditSpan
    owner: int


@dataclass
class _Refusal:
    reasons: tuple[Reason, ...]
    conflicts_with: tuple[int, ...] = ()


def run_batch(actions: Sequence[BatchAction], workspace: Workspace, *, best_effort: bool = False) -> BatchResult:
    """Runs the actions together on the workspace, which is not modified.

    Atomic by default: if any action is refused, the result has no edits. With `best_effort`, the edits of the actions
    that succeed without conflict are kept.
    """
    return _Batch(actions, workspace).run(best_effort)


class _Batch:
    def __init__(self, actions: Sequence[BatchAction], workspace: Workspace) -> None:
        self.actions = list(actions)
        self.snapshot = workspace
        self.refusals: dict[int, _Refusal] = {}
        self.rename_plans: dict[int, RenamePlan] = {}
        self.refused_alone_for_collision: dict[int, RefusalError] = {}
        self.extractions: dict[int, _Extraction] = {}
        self.applied: dict[str, list[_AppliedSpan]] = {}
        self.rename_spans_cache: dict[int, list[_Span]] = {}

    def line(self, index: int) -> int:
        return self.actions[index].line

    def lines(self, indexes: Iterable[int]) -> tuple[int, ...]:
        return tuple(sorted({self.line(index) for index in indexes}))

    def location(self, index: int) -> Location | None:
        request = self.actions[index].request
        if isinstance(request, RenameRequest):
            return Location(request.file, request.position, request.position)
        if isinstance(request, ExtractIifeRequest):
            return Location(request.file, request.start, request.end)
        return None

    def refuse(self, index: int, code: str, message: str, conflicts_with: Iterable[int] = ()) -> None:
        reason = Reason(code, message, self.location(index))
        self.refusals[index] = _Refusal((reason,), self.lines(conflicts_with))

    def describe_lines(self, indexes: Iterable[int]) -> str:
        return ", ".join(str(line) for line in self.lines(indexes))

    def run(self, best_effort: bool) -> BatchResult:
        for index, action in enumerate(self.actions):
            self.check_alone(index, action)
        self.refuse_overlaps()
        self.combine_renames()
        self.compose_extractions()
        return self.result(best_effort)

    # ---- 1. each action alone, on the snapshot ----

    def check_alone(self, index: int, action: BatchAction) -> None:
        request = action.request
        if request is None:
            self.refuse(index, RefusalCodes.NOT_IMPLEMENTED, f"The refactoring {action.refactoring!r} is not implemented.")
            return
        if isinstance(request, RenameRequest):
            try:
                plan = plan_rename(request, self.snapshot)
            except RefusalError as refusal:
                self.refusals[index] = _Refusal((refusal.to_reason(),))
                return
            try:
                verify_rename_plan(self.snapshot, plan)
            except RefusalError as refusal:
                if refusal.code != RenameRefusalCodes.BINDING_WOULD_CHANGE:
                    self.refusals[index] = _Refusal((refusal.to_reason(),))
                    return
                self.refused_alone_for_collision[index] = refusal
            self.rename_plans[index] = plan
            return
        result = extract_iife(request, self.snapshot)
        if isinstance(result, Refused):
            self.refusals[index] = _Refusal(result.reasons)
            return
        if len(result.edits) != 1:
            raise RefusalError(RefusalCodes.INTERNAL_VERIFICATION_FAILED, "Extract IIFE did not produce exactly one edit.")
        file = self.snapshot.file(request.file)
        edit = result.edits[0]
        self.extractions[index] = _Extraction(
            file.offset_of_position(request.start),
            file.offset_of_position(request.end),
            _Span(file.path, file.offset_of_position(edit.start), file.offset_of_position(edit.end)),
        )

    def rename_spans(self, index: int) -> list[_Span]:
        cached = self.rename_spans_cache.get(index)
        if cached is not None:
            return cached
        spans = []
        for edit in self.rename_plans[index].edits:
            file = self.snapshot.file(edit.file)
            spans.append(_Span(file.path, file.offset_of_position(edit.start), file.offset_of_position(edit.end)))
        self.rename_spans_cache[index] = spans
        return spans

    # ---- 2. textual overlap ----

    def refuse_overlaps(self) -> None:
        kept: list[int] = []
        for index in range(len(self.actions)):
            if index in self.refusals:
                continue
            overlapping = [other for other in kept if self.overlap(other, index)]
            if overlapping:
                self.refuse(
                    index,
                    BatchRefusalCodes.EDITS_OVERLAP,
                    f"The action edits text that line {self.describe_lines(overlapping)} also edits.",
                    overlapping,
                )
            else:
                kept.append(index)

    def overlap(self, first: int, second: int) -> bool:
        if first in self.rename_plans and second in self.rename_plans:
            return any(a.intersects(b) for a in self.rename_spans(first) for b in self.rename_spans(second))
        if first in self.extractions and second in self.extractions:
            return self.extractions[first].region.intersects(self.extractions[second].region)
        rename, extraction = (first, second) if first in self.rename_plans else (second, first)
        return self.rename_overlaps_extraction(self.rename_spans(rename), self.extractions[extraction])

    @staticmethod
    def rename_overlaps_extraction(spans: list[_Span], extraction: _Extraction) -> bool:
        region = extraction.region
        boundaries = (extraction.selection_start, extraction.selection_end, region.start, region.end)
        for span in spans:
            if span.intersects(region) and not region.contains(span):
                return True
            if any(span.strictly_contains_offset(region.file, offset) for offset in boundaries):
                return True
        return False

    # ---- 3. renames, verified together ----

    def combination_failure(self, indexes: Sequence[int]) -> RefusalError | None:
        """None when the renames together pass the re-binding check, else the failure."""
        edits: list[TextEdit] = []
        renamed_symbols: dict[Symbol, str] = {}
        for index in indexes:
            edits.extend(self.rename_plans[index].edits)
            renamed_symbols.update(self.rename_plans[index].renamed_symbols)
        if not edits:
            return None
        try:
            verify_edits(self.snapshot, edits, renamed_symbols=renamed_symbols)
        except RefusalError as failure:
            return failure
        return None

    def candidate_renames(self) -> list[int]:
        return sorted(index for index in self.rename_plans if index not in self.refusals)

    def combine_renames(self) -> None:
        candidates = self.candidate_renames()
        fine_alone = [index for index in candidates if index not in self.refused_alone_for_collision]
        colliding_alone = [index for index in candidates if index in self.refused_alone_for_collision]
        accepted: list[int] = []
        if self.combination_failure(fine_alone) is None:
            accepted = list(fine_alone)
        else:
            for index in fine_alone:
                failure = self.combination_failure([*accepted, index])
                if failure is None:
                    accepted.append(index)
                    continue
                partners = [other for other in accepted if self.combination_failure([other, index]) is not None]
                self.refuse(
                    index,
                    BatchRefusalCodes.SEMANTIC_CONFLICT,
                    f"Together with line {self.describe_lines(partners or accepted)}, the rename would change what a name "
                    f"refers to: {failure.message}",
                    partners or accepted,
                )
        for group in self.groups_linked_by_name(colliding_alone):
            if self.combination_failure([*accepted, *group]) is None:
                accepted.extend(group)
                continue
            for index in group:
                refusal = self.refused_alone_for_collision[index]
                self.refusals[index] = _Refusal((refusal.to_reason(),))
        for index in accepted:
            for edit in self.rename_plans[index].edits:
                file = self.snapshot.file(edit.file)
                span = EditSpan(file.offset_of_position(edit.start), file.offset_of_position(edit.end), edit.new_text)
                self.applied.setdefault(file.path, []).append(_AppliedSpan(span, index))

    def groups_linked_by_name(self, indexes: list[int]) -> list[list[int]]:
        """Groups the renames where one's new name is another's old name, or two have the same new name (as in a swap)."""
        group_of = {index: index for index in indexes}

        def root(index: int) -> int:
            while group_of[index] != index:
                index = group_of[index]
            return index

        names = {index: self.names_of(index) for index in indexes}
        for first in indexes:
            for second in indexes:
                if first < second and names[first] & names[second]:
                    group_of[root(second)] = root(first)
        groups: dict[int, list[int]] = {}
        for index in indexes:
            groups.setdefault(root(index), []).append(index)
        return list(groups.values())

    def names_of(self, index: int) -> set[str]:
        plan = self.rename_plans[index]
        return {symbol.name for symbol in plan.renamed_symbols} | set(plan.renamed_symbols.values())

    # ---- 4. extractions, on the result of the edits before them ----

    def current_texts(self, paths: Iterable[str]) -> dict[str, str]:
        return {
            path: apply_spans(self.snapshot.files[path].text, [applied.span for applied in self.applied.get(path, [])])
            for path in paths
        }

    def map_offset(self, path: str, offset: int) -> int:
        delta = 0
        for applied in self.applied.get(path, []):
            span = applied.span
            if span.end_offset <= offset:
                delta += len(span.new_text) - (span.end_offset - span.start_offset)
        return offset + delta

    def compose_extractions(self) -> None:
        pending = [index for index in self.extractions if index not in self.refusals]
        if not pending:
            return
        current = self.snapshot.with_texts(self.current_texts(self.applied))
        pending.sort(key=lambda index: (self.extractions[index].region.file, self.extractions[index].region.start))
        for index in pending:
            current = self.compose_extraction(index, current)

    def compose_extraction(self, index: int, current: Workspace) -> Workspace:
        extraction = self.extractions[index]
        path = extraction.region.file
        others = {applied.owner for applied in self.applied.get(path, [])}
        if not others:
            others = {applied.owner for spans in self.applied.values() for applied in spans}
        current_file = current.file(path)
        request = ExtractIifeRequest(
            path,
            current_file.position_of_offset(self.map_offset(path, extraction.selection_start)),
            current_file.position_of_offset(self.map_offset(path, extraction.selection_end)),
        )
        result = extract_iife(request, current)
        if isinstance(result, Refused):
            reason = result.reasons[0]
            self.refuse(
                index,
                BatchRefusalCodes.SEMANTIC_CONFLICT,
                f"After the edits of line {self.describe_lines(others)}, Extract IIFE refuses: [{reason.code}] {reason.message}",
                others,
            )
            return current
        edit = result.edits[0]
        expected_start = self.map_offset(path, extraction.region.start)
        expected_end = self.map_offset(path, extraction.region.end)
        actual = (current_file.offset_of_position(edit.start), current_file.offset_of_position(edit.end))
        if len(result.edits) != 1 or edit.file != path or actual != (expected_start, expected_end):
            self.refuse(
                index,
                BatchRefusalCodes.SEMANTIC_CONFLICT,
                f"After the edits of line {self.describe_lines(others)}, Extract IIFE replaces different text.",
                others,
            )
            return current
        region = extraction.region
        kept = [
            applied
            for applied in self.applied.get(path, [])
            if not region.contains(_Span(path, applied.span.start_offset, applied.span.end_offset))
        ]
        kept.append(_AppliedSpan(EditSpan(region.start, region.end, edit.new_text), index))
        self.applied[path] = sorted(kept, key=lambda applied: applied.span.start_offset)
        new_text = self.current_texts([path])[path]
        if new_text != current.apply_edits(result.edits)[path]:
            raise RefusalError(
                RefusalCodes.INTERNAL_VERIFICATION_FAILED, "The batch's edits do not reproduce the composed extraction."
            )
        extraction.warnings = result.warnings
        return current.with_texts({path: new_text})

    # ---- the result ----

    def edits_of(self, index: int) -> tuple[TextEdit, ...]:
        edits = []
        for path, spans in sorted(self.applied.items()):
            for applied in spans:
                if applied.owner == index:
                    span = applied.span
                    edits.append(self.snapshot.edit(path, span.start_offset, span.end_offset, span.new_text))
        return tuple(edits)

    def warnings_of(self, index: int) -> tuple[RefactoringWarning, ...]:
        if index in self.rename_plans:
            return self.rename_plans[index].warnings
        return self.extractions[index].warnings

    def result(self, best_effort: bool) -> BatchResult:
        root = self.snapshot.root_text
        results = []
        for index, action in enumerate(self.actions):
            refusal = self.refusals.get(index)
            if refusal is not None:
                results.append(ActionResult(action.line, action.refactoring, Refused(root, refusal.reasons), refusal.conflicts_with))
            else:
                success = Success(root, self.edits_of(index), self.warnings_of(index))
                results.append(ActionResult(action.line, action.refactoring, success))
        succeeded = [action for action in results if isinstance(action.result, Success)]
        if not self.refusals:
            status = BatchStatus.SUCCESS
        elif best_effort and succeeded:
            status = BatchStatus.PARTIAL
        else:
            status = BatchStatus.REFUSED
        edits: tuple[TextEdit, ...] = ()
        warnings: tuple[RefactoringWarning, ...] = ()
        if status != BatchStatus.REFUSED:
            edits = tuple(edit for action in succeeded for edit in action.result.edits)  # type: ignore[union-attr]
            edits = tuple(sorted(edits, key=lambda edit: (edit.file, edit.start, edit.end)))
            warnings = tuple(warning for action in succeeded for warning in action.result.warnings)  # type: ignore[union-attr]
        return BatchResult(root, status, edits, warnings, tuple(results))
