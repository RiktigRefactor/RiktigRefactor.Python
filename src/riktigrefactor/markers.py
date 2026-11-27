"""Python selection markers of the test format (see the specification's test-format.md).

Single-line selection, as a trailing comment that quotes the selected text:
    total = price * qty + shipping  # [price * qty]
    total = x + x                    # [x]#2      (second occurrence)
    print(count)                     # |count     (cursor at the start of "count"; `|count#2` for the second)
Multi-line selection, as whole lines between two marker lines:
    # [
    a = f(x)
    b = g(a)
    # ]
The marker comment, and the whitespace before it, is removed; the marker lines are removed with their line breaks.
A multi-line selection runs from the start of its first line to the end of the text of its last line.
"""

import io
import re
import tokenize
from dataclasses import dataclass

from riktigrefactor.protocol import Position

_LINE_WITH_BREAK = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
_RANGE_START_LINE = re.compile(r"^#\s*\[\s*$")
_RANGE_END_LINE = re.compile(r"^#\s*\]\s*$")
_QUOTED_SELECTION = re.compile(r"^#\s?\[(?P<text>.+)\](?:#(?P<occurrence>\d+))?\s*$")
_CURSOR = re.compile(r"^#\s?\|(?P<text>.+?)(?:#(?P<occurrence>\d+))?\s*$")
_POSSIBLE_MARKER = re.compile(r"#\s?[\[\]|]")


class MarkerError(ValueError):
    pass


@dataclass(frozen=True)
class Selection:
    """A cursor has `start == end`."""

    start: Position
    end: Position


def may_contain_markers(text: str) -> bool:
    return _POSSIBLE_MARKER.search(text) is not None


def _comment_tokens_by_line(text: str) -> dict[int, tuple[int, str]]:
    comments = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                comments[token.start[0]] = (token.start[1], token.string)
    except (tokenize.TokenError, SyntaxError) as error:
        raise MarkerError(f"cannot tokenize the text to find markers: {error}") from error
    return comments


def _text_without_line_break(line: str) -> str:
    return line.rstrip("\r\n")


def _find_at_word_boundaries(code: str, quoted: str, search_from: int) -> int:
    """The first match of `quoted` from `search_from`; an identifier-like `quoted` must not touch other identifier characters.

    `# |e` therefore finds the name `e` and not the `e` inside `except`; if the line has no such name, the first
    substring match is used, as before.
    """
    if not (quoted[0].isidentifier() or quoted[0].isdigit()) or not (quoted[-1].isidentifier() or quoted[-1].isdigit()):
        return code.find(quoted, search_from)
    first_substring = code.find(quoted, search_from)
    index = first_substring
    while index >= 0:
        before = code[index - 1] if index > 0 else ""
        after = code[index + len(quoted)] if index + len(quoted) < len(code) else ""
        if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
            return index
        index = code.find(quoted, index + 1)
    return first_substring


def _nth_occurrence(code: str, quoted: str, occurrence: int, line_number: int) -> int:
    index = -1
    search_from = 0
    for _ in range(occurrence):
        # An explicit `#n` counts plain substring matches, as it always did.
        index = _find_at_word_boundaries(code, quoted, search_from) if occurrence == 1 else code.find(quoted, search_from)
        if index < 0:
            raise MarkerError(f"line {line_number}: {quoted!r} does not occur {occurrence} time(s) before the marker")
        search_from = index + len(quoted)
    return index


def strip_markers(text: str) -> tuple[str, Selection | None]:
    """Returns the text without markers and the selection they mark (None if there are no markers)."""
    if not may_contain_markers(text):
        return text, None
    comments = _comment_tokens_by_line(text)
    lines = _LINE_WITH_BREAK.findall(text)
    output_lines: list[str] = []
    selection: Selection | None = None
    range_start_line: int | None = None
    for line_number, line in enumerate(lines, start=1):
        comment = comments.get(line_number)
        if comment is None:
            output_lines.append(line)
            continue
        column, comment_text = comment
        line_text = _text_without_line_break(line)
        line_break = line[len(line_text) :]
        is_comment_only = line_text.strip() == comment_text
        if is_comment_only and _RANGE_START_LINE.match(comment_text):
            if range_start_line is not None:
                raise MarkerError(f"line {line_number}: a second range start marker")
            range_start_line = len(output_lines) + 1
            continue
        if is_comment_only and _RANGE_END_LINE.match(comment_text):
            if range_start_line is None or len(output_lines) < range_start_line:
                raise MarkerError(f"line {line_number}: a range end marker without selected lines")
            if selection is not None:
                raise MarkerError(f"line {line_number}: more than one selection")
            last_line = _text_without_line_break(output_lines[-1])
            selection = Selection(Position(range_start_line, 1), Position(len(output_lines), len(last_line) + 1))
            range_start_line = None
            continue
        quoted = _QUOTED_SELECTION.match(comment_text)
        cursor = None if quoted else _CURSOR.match(comment_text)
        found = quoted or cursor
        if found is None:
            output_lines.append(line)
            continue
        if selection is not None or range_start_line is not None:
            raise MarkerError(f"line {line_number}: more than one selection")
        code = line_text[:column].rstrip()
        occurrence = int(found.group("occurrence") or 1)
        index = _nth_occurrence(code, found.group("text"), occurrence, line_number)
        output_line_number = len(output_lines) + 1
        start = Position(output_line_number, index + 1)
        if quoted:
            end = Position(output_line_number, index + len(found.group("text")) + 1)
        else:
            end = start
        selection = Selection(start, end)
        output_lines.append(code + line_break)
    if range_start_line is not None:
        raise MarkerError("a range start marker without an end marker")
    return "".join(output_lines), selection
