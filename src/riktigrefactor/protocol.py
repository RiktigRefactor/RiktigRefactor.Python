"""Request and result types of the RiktigRefactor protocol (see the specification's protocol.md).

Lines and columns are 1-based; columns count Unicode scalar values (Python `str` indexes).
Every `file` is relative to the workspace root and uses "/" as the separator.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from typing import Any


class RefusalCodes:
    """Codes shared by every refactoring; refusal-codes.md at the repository root is the source of truth."""

    INTERNAL_VERIFICATION_FAILED = "internal-verification-failed"
    NO_SYMBOL = "no-symbol"
    INVALID_SELECTION = "invalid-selection"
    FILE_NOT_FOUND = "file-not-found"
    FILE_NOT_PARSEABLE = "file-not-parseable"
    UNSUPPORTED_ENCODING = "unsupported-encoding"
    AMBIGUOUS_MODULE_NAME = "ambiguous-module-name"
    UNSUPPORTED_SCOPING = "unsupported-scoping"
    NOT_IMPLEMENTED = "not-implemented"


@dataclass(frozen=True, order=True)
class Position:
    line: int
    column: int

    def to_json(self) -> dict[str, int]:
        return {"line": self.line, "column": self.column}


@dataclass(frozen=True)
class Location:
    file: str
    start: Position
    end: Position

    def to_json(self) -> dict[str, Any]:
        return {"file": self.file, "start": self.start.to_json(), "end": self.end.to_json()}


@dataclass(frozen=True)
class TextEdit:
    file: str
    start: Position
    end: Position
    new_text: str

    def to_json(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "start": self.start.to_json(),
            "end": self.end.to_json(),
            "newText": self.new_text,
        }


@dataclass(frozen=True)
class RefactoringWarning:
    code: str
    message: str
    location: Location | None = None

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.location is not None:
            result["location"] = self.location.to_json()
        return result


@dataclass(frozen=True)
class Reason:
    code: str
    message: str
    location: Location | None = None
    suggestion: str | None = None

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.location is not None:
            result["location"] = self.location.to_json()
        if self.suggestion is not None:
            result["suggestion"] = self.suggestion
        return result


@dataclass(frozen=True)
class Success:
    workspace_root: str
    edits: tuple[TextEdit, ...]
    warnings: tuple[RefactoringWarning, ...] = ()
    status: str = field(default="success", init=False)

    def to_json(self) -> dict[str, Any]:
        return {
            "status": "success",
            "workspaceRoot": self.workspace_root,
            "edits": [edit.to_json() for edit in self.edits],
            "warnings": [warning.to_json() for warning in self.warnings],
        }


@dataclass(frozen=True)
class Refused:
    workspace_root: str
    reasons: tuple[Reason, ...]
    status: str = field(default="refused", init=False)

    def to_json(self) -> dict[str, Any]:
        return {
            "status": "refused",
            "workspaceRoot": self.workspace_root,
            "reasons": [reason.to_json() for reason in self.reasons],
        }


Result = Success | Refused


def to_json(result: Result) -> dict[str, Any]:
    return result.to_json()


@dataclass(frozen=True)
class RenameRequest:
    file: str
    position: Position
    new_name: str

    def to_json(self, workspace: str) -> dict[str, Any]:
        location = Location(self.file, self.position, self.position)
        return {
            "refactoring": "rename",
            "workspace": workspace,
            "location": location.to_json(),
            "options": {"newName": self.new_name},
        }


@dataclass(frozen=True)
class ExtractIifeRequest:
    file: str
    start: Position
    end: Position

    def to_json(self, workspace: str) -> dict[str, Any]:
        return {
            "refactoring": "extract-iife",
            "workspace": workspace,
            "location": Location(self.file, self.start, self.end).to_json(),
            "options": {},
        }


class RefusalError(Exception):
    """Raised anywhere inside a refactoring to refuse; `returning_refusals` turns it into a `Refused` result."""

    def __init__(
        self,
        code: str,
        message: str,
        location: Location | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.location = location
        self.suggestion = suggestion

    def to_reason(self) -> Reason:
        return Reason(self.code, self.message, self.location, self.suggestion)


class SemanticModelError(RefusalError):
    """The scope analysis cannot model a construct or disagrees with CPython's `symtable`; refactorings must not proceed."""

    def __init__(self, message: str, location: Location | None = None) -> None:
        super().__init__(RefusalCodes.UNSUPPORTED_SCOPING, message, location)


def returning_refusals(refactoring: Callable[[Any, Any], Result]) -> Callable[[Any, Any], Result]:
    """Decorates `refactoring(request, workspace)` so that a raised `RefusalError` becomes a `Refused` result."""

    @wraps(refactoring)
    def run(request: Any, workspace: Any) -> Result:
        try:
            return refactoring(request, workspace)
        except RefusalError as refusal:
            return Refused(workspace.root_text, (refusal.to_reason(),))

    return run
