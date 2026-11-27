"""Deliberately naive implementations of each refactoring, used to check that edge-case tests can fail.

A case with `"naiveShouldFail": true` passes only if the program that results from the naive implementation
fails (or does not compile). Each function returns the new text of every file it changes, keyed by path
relative to the workspace root, or raises `NotImplementedError` until its agent fills it in.
"""

import ast
import io
import tokenize

from riktigrefactor.extract_iife import locate_selection
from riktigrefactor.protocol import ExtractIifeRequest, Position, RenameRequest
from riktigrefactor.workspace import Workspace


def naive_rename(workspace: Workspace, request: RenameRequest) -> dict[str, str]:
    """Textually replaces every identifier token that has the same spelling as the one at the cursor, in every file."""
    source = workspace.file(request.file)
    cursor = source.offset_of_position(request.position)
    old_spelling = None
    for token in _name_tokens(source):
        start = source.offset_of_position(Position(*_one_based(token.start)))
        if start <= cursor <= start + len(token.string):
            old_spelling = token.string
    if old_spelling is None:
        raise NotImplementedError("the cursor is not on an identifier")
    changed = {}
    for path, file in workspace.files.items():
        pieces = []
        copied_up_to = 0
        for token in _name_tokens(file):
            if token.string != old_spelling:
                continue
            start = file.offset_of_position(Position(*_one_based(token.start)))
            pieces.append(file.text[copied_up_to:start])
            pieces.append(request.new_name)
            copied_up_to = start + len(token.string)
        if pieces:
            pieces.append(file.text[copied_up_to:])
            changed[path] = "".join(pieces)
    return changed


def _name_tokens(file) -> list[tokenize.TokenInfo]:
    return [
        token
        for token in tokenize.generate_tokens(io.StringIO(file.text).readline)
        if token.type == tokenize.NAME
    ]


def _one_based(token_start: tuple[int, int]) -> tuple[int, int]:
    return token_start[0], token_start[1] + 1


def naive_extract_iife(workspace: Workspace, request: ExtractIifeRequest) -> dict[str, str]:
    """Wraps the selection in a lambda or def that is passed every local it reads, returns nothing, and checks nothing.

    An expression becomes `(lambda a, b: <expr>)(a, b)` and statements become `def _extracted1(a, b): ...` followed by
    `_extracted1(a, b)`: reads are passed, but writes are lost, and no precondition is checked.
    """
    selection = locate_selection(request, workspace)
    text = selection.file.text
    parents = selection.parents
    enclosing: ast.AST | None = parents.get(id(selection.anchor))
    while enclosing is not None and not isinstance(
        enclosing, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Module)
    ):
        enclosing = parents.get(id(enclosing))
    assert enclosing is not None
    local_names = {n.id for n in ast.walk(enclosing) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    local_names |= {n.arg for n in ast.walk(enclosing) if isinstance(n, ast.arg)}
    roots = list(selection.statements) if selection.statements else [selection.expression]
    parameters: list[str] = []
    for root in roots:
        for node in ast.walk(root):
            if isinstance(node, ast.Name) and node.id in local_names and node.id not in parameters:
                parameters.append(node.id)
    arguments = ", ".join(parameters)
    path = selection.file.path
    if selection.expression is not None:
        body = text[selection.start : selection.end]
        if isinstance(selection.expression, ast.Tuple):
            body = f"({body})"
        replacement = f"(lambda {arguments}: {body})({arguments})"
        return {path: text[: selection.start] + replacement + text[selection.end :]}
    prefix = text[text.rfind("\n", 0, selection.start) + 1 : selection.start]
    first, *rest = text[selection.start : selection.end].split("\n")
    body = first + "".join("\n" + ("    " + line if line.strip() else line) for line in rest)
    replacement = f"def _extracted1({arguments}):\n{prefix}    {body}\n{prefix}_extracted1({arguments})"
    return {path: text[: selection.start] + replacement + text[selection.end :]}
