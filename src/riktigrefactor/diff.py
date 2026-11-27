"""Unified diffs of workspace texts, for the command line's preview."""

import difflib
import re
from collections.abc import Mapping

_LINE_WITH_BREAK = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
_NO_NEWLINE_MARKER = "\\ No newline at end of file\n"


def _lines(text: str) -> list[str]:
    return _LINE_WITH_BREAK.findall(text)


def unified_diff(old_texts: Mapping[str, str], new_texts: Mapping[str, str]) -> str:
    """A unified diff of every path whose text differs, with `a/` and `b/` prefixes, in path order."""
    pieces = []
    for path in sorted(set(old_texts) | set(new_texts)):
        old = old_texts.get(path, "")
        new = new_texts.get(path, "")
        if old == new:
            continue
        for line in difflib.unified_diff(_lines(old), _lines(new), f"a/{path}", f"b/{path}"):
            if line.endswith("\n"):
                pieces.append(line)
            else:
                pieces.append(line + "\n" + _NO_NEWLINE_MARKER)
    return "".join(pieces)
