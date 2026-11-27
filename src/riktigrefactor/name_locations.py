"""Finds the source spans of identifiers that `ast` stores as bare strings, without positions.

Each function returns (start_offset, end_offset, spelling) where the spelling is as written in the source;
the parser NFKC-normalizes identifiers, so the spelling can differ from the name in the tree.
"""

import re
import unicodedata

from riktigrefactor.workspace import SourceFile

IDENTIFIER = r"[^\W\d]\w*"
_WHITESPACE_OR_CONTINUATION = r"(?:[ \t\f]|\\\r\n|\\\r|\\\n)+"
_DEFINITION = {
    "def": re.compile(rf"(?:async{_WHITESPACE_OR_CONTINUATION})?def{_WHITESPACE_OR_CONTINUATION}({IDENTIFIER})"),
    "class": re.compile(rf"class{_WHITESPACE_OR_CONTINUATION}({IDENTIFIER})"),
}
_IDENTIFIER_OR_COMMENT = re.compile(rf"#[^\r\n]*|({IDENTIFIER})")
_IDENTIFIER_AT_END = re.compile(rf"{IDENTIFIER}\Z")
_IDENTIFIER_AFTER_STARS = re.compile(rf"\*{{0,2}}\s*({IDENTIFIER})")
_IDENTIFIER_AT_START = re.compile(IDENTIFIER)
_EXCEPT_AS_NAME = re.compile(
    rf"(?:[\s)]|\\\r\n|\\\r|\\\n|#[^\r\n]*)*as(?:\s|\\\r\n|\\\r|\\\n)+({IDENTIFIER})"
)
_MAPPING_REST = re.compile(rf"\*\*(?:\s|\\\r\n|\\\r|\\\n|#[^\r\n]*)*({IDENTIFIER})")
_MAXIMUM_IDENTIFIER_LENGTH_TO_SCAN_BACK = 4096

Span = tuple[int, int, str]


class NameNotFoundInSource(Exception):
    pass


def normalized(spelling: str) -> str:
    return unicodedata.normalize("NFKC", spelling)


def _checked(file: SourceFile, start: int, end: int, expected_name: str) -> Span:
    spelling = file.text[start:end]
    if normalized(spelling) != expected_name:
        raise NameNotFoundInSource(f"{file.path}: expected {expected_name} at offset {start}, found {spelling}")
    return start, end, spelling


def identifier_at_start(file: SourceFile, offset: int, expected_name: str) -> Span:
    match = _IDENTIFIER_AT_START.match(file.text, offset)
    if match is None:
        raise NameNotFoundInSource(f"{file.path}: no identifier at offset {offset}")
    return _checked(file, match.start(), match.end(), expected_name)


def identifier_before(file: SourceFile, end_offset: int, expected_name: str) -> Span:
    window_start = max(0, end_offset - _MAXIMUM_IDENTIFIER_LENGTH_TO_SCAN_BACK)
    match = _IDENTIFIER_AT_END.search(file.text[window_start:end_offset])
    if match is None:
        raise NameNotFoundInSource(f"{file.path}: no identifier ends at offset {end_offset}")
    return _checked(file, window_start + match.start(), end_offset, expected_name)


def definition_name(file: SourceFile, node_start_offset: int, keyword: str, expected_name: str) -> Span:
    match = _DEFINITION[keyword].match(file.text, node_start_offset)
    if match is None:
        raise NameNotFoundInSource(f"{file.path}: no {keyword} statement at offset {node_start_offset}")
    return _checked(file, match.start(1), match.end(1), expected_name)


def identifiers_in(file: SourceFile, start_offset: int, end_offset: int) -> list[Span]:
    """Identifier-shaped words in the fragment, skipping comments; keywords such as `as` are included."""
    spans = []
    for match in _IDENTIFIER_OR_COMMENT.finditer(file.text, start_offset, end_offset):
        if match.group(1) is not None:
            spans.append((match.start(1), match.end(1), match.group(1)))
    return spans


def declared_names(file: SourceFile, statement_start: int, statement_end: int, names: list[str]) -> list[Span]:
    """The names of a `global` or `nonlocal` statement, in order."""
    words = identifiers_in(file, statement_start, statement_end)[1:]
    if len(words) != len(names):
        raise NameNotFoundInSource(f"{file.path}: cannot match the names of the statement at offset {statement_start}")
    return [_checked(file, start, end, name) for (start, end, _), name in zip(words, names, strict=True)]


def import_alias_names(file: SourceFile, alias_start: int, alias_end: int, name: str, as_name: str | None):
    """Returns (span of the first part of the imported name, span of the name after `as` or None)."""
    words = identifiers_in(file, alias_start, alias_end)
    if not words:
        raise NameNotFoundInSource(f"{file.path}: empty import alias at offset {alias_start}")
    first = words[0]
    if as_name is None:
        return first, None
    if len(words) < 3 or words[-2][2] != "as":
        raise NameNotFoundInSource(f"{file.path}: cannot find the name after as at offset {alias_start}")
    last = words[-1]
    return first, _checked(file, last[0], last[1], as_name)


def except_handler_name(file: SourceFile, type_end_offset: int, name: str) -> Span:
    match = _EXCEPT_AS_NAME.match(file.text, type_end_offset)
    if match is None:
        raise NameNotFoundInSource(f"{file.path}: cannot find the name after as at offset {type_end_offset}")
    return _checked(file, match.start(1), match.end(1), name)


def type_parameter_name(file: SourceFile, node_start_offset: int, name: str) -> Span:
    match = _IDENTIFIER_AFTER_STARS.match(file.text, node_start_offset)
    if match is None:
        raise NameNotFoundInSource(f"{file.path}: no type parameter at offset {node_start_offset}")
    return _checked(file, match.start(1), match.end(1), name)


def mapping_pattern_rest(file: SourceFile, pattern_start: int, pattern_end: int, name: str) -> Span:
    last = None
    for last in _MAPPING_REST.finditer(file.text, pattern_start, pattern_end):
        pass
    if last is None:
        raise NameNotFoundInSource(f"{file.path}: no ** rest in the pattern at offset {pattern_start}")
    return _checked(file, last.start(1), last.end(1), name)
