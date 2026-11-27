"""RiktigRefactor for Python: seriously safe behavior-preserving refactorings.

The refactorings are in riktigrefactor.rename (`rename`) and riktigrefactor.extract_iife (`extract_iife`); they are not
re-exported here, because a function named like its module would hide the module.
"""

from riktigrefactor.protocol import (
    ExtractIifeRequest,
    Location,
    Position,
    Reason,
    Refused,
    RefusalError,
    RenameRequest,
    Result,
    Success,
    TextEdit,
)
from riktigrefactor.workspace import Workspace

__all__ = [
    "ExtractIifeRequest",
    "Location",
    "Position",
    "Reason",
    "Refused",
    "RefusalError",
    "RenameRequest",
    "Result",
    "Success",
    "TextEdit",
    "Workspace",
]
