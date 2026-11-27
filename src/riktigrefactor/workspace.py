"""Loading a Python workspace: files, module names, and position/offset conversion.

Offsets are indexes into `SourceFile.text` (Unicode scalar values).
`ast` columns are UTF-8 byte offsets; `SourceFile.offset_of_ast_position` converts them.
"""

import ast
import bisect
import io
import re
import tokenize
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from riktigrefactor.protocol import Location, Position, RefusalCodes, RefusalError, TextEdit

_LINE_BREAK = re.compile(r"\r\n|\r|\n")
_NOT_SOURCE_DIRECTORY_NAMES = {"__pycache__", "node_modules", "site-packages", "build", "dist"}
_UTF8_BYTE_ORDER_MARK = "﻿"


@dataclass(frozen=True)
class EditSpan:
    start_offset: int
    end_offset: int
    new_text: str


class SourceFile:
    def __init__(
        self,
        path: str,
        text: str,
        module_name: str | None,
        is_package_initializer: bool,
        has_byte_order_mark: bool = False,
    ) -> None:
        self.path = path
        self.text = text
        self.module_name = module_name
        self.is_package_initializer = is_package_initializer
        self.has_byte_order_mark = has_byte_order_mark
        self._line_starts = [0] + [match.end() for match in _LINE_BREAK.finditer(text)]
        self._line_bytes_cache: dict[int, bytes] = {}
        self.tree = self._parse()

    @property
    def module_key(self) -> str:
        """Identity of the module: its dotted name, or a path-based key when the file is not importable."""
        if self.module_name is not None:
            return self.module_name
        return f"<file:{self.path}>"

    @property
    def containing_package_name(self) -> str:
        """The package that relative imports in this file are relative to ("" for a top-level module)."""
        if self.module_name is None:
            return ""
        if self.is_package_initializer:
            return self.module_name
        return self.module_name.rpartition(".")[0]

    def _parse(self) -> ast.Module:
        try:
            return ast.parse(self.text, filename=self.path, type_comments=False)
        except (SyntaxError, ValueError) as error:
            line = getattr(error, "lineno", None) or 1
            column = getattr(error, "offset", None) or 1
            position = Position(line, column)
            raise RefusalError(
                RefusalCodes.FILE_NOT_PARSEABLE,
                f"{self.path} does not parse: {error}",
                Location(self.path, position, position),
            ) from error

    @property
    def line_count(self) -> int:
        return len(self._line_starts)

    def line_start_offset(self, line: int) -> int:
        return self._line_starts[line - 1]

    def line_text_end_offset(self, line: int) -> int:
        """Offset just before the line break that ends the line (or the end of the text)."""
        if line < len(self._line_starts):
            next_start = self._line_starts[line]
            end = next_start
            if self.text[end - 1] == "\n":
                end -= 1
                if end > self._line_starts[line - 1] and self.text[end - 1] == "\r":
                    end -= 1
            elif self.text[end - 1] == "\r":
                end -= 1
            return end
        return len(self.text)

    def position_of_offset(self, offset: int) -> Position:
        if not 0 <= offset <= len(self.text):
            raise ValueError(f"offset {offset} is outside {self.path}")
        line_index = bisect.bisect_right(self._line_starts, offset) - 1
        return Position(line_index + 1, offset - self._line_starts[line_index] + 1)

    def offset_of_position(self, position: Position) -> int:
        if not 1 <= position.line <= len(self._line_starts) or position.column < 1:
            raise self._invalid_position(position)
        offset = self._line_starts[position.line - 1] + position.column - 1
        if offset > self.line_text_end_offset(position.line):
            raise self._invalid_position(position)
        return offset

    def _invalid_position(self, position: Position) -> RefusalError:
        return RefusalError(
            RefusalCodes.INVALID_SELECTION,
            f"{position.line}:{position.column} is not a position in {self.path}.",
        )

    def offset_of_ast_position(self, line: int, utf8_column: int) -> int:
        line_start = self._line_starts[line - 1]
        if utf8_column == 0:
            return line_start
        line_end = self._line_starts[line] if line < len(self._line_starts) else len(self.text)
        line_text = self.text[line_start:line_end]
        if line_text.isascii():
            return line_start + utf8_column
        line_bytes = self._line_bytes_cache.get(line)
        if line_bytes is None:
            line_bytes = line_text.encode("utf-8")
            self._line_bytes_cache[line] = line_bytes
        return line_start + len(line_bytes[:utf8_column].decode("utf-8"))

    def start_offset(self, node: Any) -> int:
        return self.offset_of_ast_position(node.lineno, node.col_offset)

    def end_offset(self, node: Any) -> int:
        return self.offset_of_ast_position(node.end_lineno, node.end_col_offset)

    def location_of_offsets(self, start_offset: int, end_offset: int) -> Location:
        return Location(self.path, self.position_of_offset(start_offset), self.position_of_offset(end_offset))

    def location_of_node(self, node: Any) -> Location:
        return self.location_of_offsets(self.start_offset(node), self.end_offset(node))


def module_name_for_path(path: str) -> tuple[str | None, bool]:
    """Returns (dotted module name or None when the path is not importable, whether it is a package `__init__.py`)."""
    parts = path.split("/")
    if len(parts) > 1 and parts[0] == "src":
        parts = parts[1:]
    stem = parts[-1][: -len(".py")]
    is_package_initializer = stem == "__init__"
    module_parts = parts[:-1] if is_package_initializer else parts[:-1] + [stem]
    if not module_parts or not all(part.isidentifier() for part in module_parts):
        return None, is_package_initializer
    return ".".join(module_parts), is_package_initializer


def _is_virtual_environment(directory: Path) -> bool:
    return (directory / "pyvenv.cfg").exists()


def _decode_source(path: str, data: bytes) -> tuple[str, bool]:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
        text = data.decode("utf-8")
    except (SyntaxError, UnicodeDecodeError) as error:
        raise RefusalError(RefusalCodes.UNSUPPORTED_ENCODING, f"{path} is not valid UTF-8 source.") from error
    if encoding not in ("utf-8", "utf-8-sig"):
        raise RefusalError(RefusalCodes.UNSUPPORTED_ENCODING, f"{path} declares the encoding {encoding}.")
    has_byte_order_mark = text.startswith(_UTF8_BYTE_ORDER_MARK)
    if has_byte_order_mark:
        text = text[1:]
    return text, has_byte_order_mark


class Workspace:
    """A project root directory and the parsed `*.py` files under it."""

    def __init__(self, root: Path, files: Iterable[SourceFile]) -> None:
        self.root = root
        self.files: dict[str, SourceFile] = {file.path: file for file in sorted(files, key=lambda f: f.path)}
        self.modules: dict[str, SourceFile] = {}
        for file in self.files.values():
            if file.module_name is None:
                continue
            existing = self.modules.get(file.module_name)
            if existing is not None:
                raise RefusalError(
                    RefusalCodes.AMBIGUOUS_MODULE_NAME,
                    f"{existing.path} and {file.path} are both the module {file.module_name}.",
                )
            self.modules[file.module_name] = file
        self.analysis_cache: dict[str, Any] = {}

    @property
    def root_text(self) -> str:
        return str(self.root)

    @staticmethod
    def load(root: str | Path) -> "Workspace":
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            raise RefusalError(RefusalCodes.FILE_NOT_FOUND, f"The workspace directory {root} does not exist.")
        files = []
        for path in sorted(Workspace._python_files(root_path)):
            relative = path.relative_to(root_path).as_posix()
            text, has_byte_order_mark = _decode_source(relative, path.read_bytes())
            module_name, is_initializer = module_name_for_path(relative)
            files.append(SourceFile(relative, text, module_name, is_initializer, has_byte_order_mark))
        return Workspace(root_path, files)

    @staticmethod
    def _python_files(directory: Path) -> Iterable[Path]:
        for entry in directory.iterdir():
            if entry.is_dir():
                if entry.name.startswith(".") or entry.name in _NOT_SOURCE_DIRECTORY_NAMES:
                    continue
                if _is_virtual_environment(entry) or entry.is_symlink():
                    continue
                yield from Workspace._python_files(entry)
            elif entry.suffix == ".py" and not entry.name.startswith("."):
                yield entry

    @staticmethod
    def from_texts(root: str | Path, texts: Mapping[str, str]) -> "Workspace":
        files = []
        for path, text in texts.items():
            module_name, is_initializer = module_name_for_path(path)
            files.append(SourceFile(path, text, module_name, is_initializer))
        return Workspace(Path(root), files)

    def with_texts(self, texts: Mapping[str, str]) -> "Workspace":
        """A workspace where the given files (relative paths) have new text; other files are shared, not re-parsed."""
        files = dict(self.files)
        for path, text in texts.items():
            old = self.files.get(path)
            module_name, is_initializer = module_name_for_path(path)
            has_byte_order_mark = old.has_byte_order_mark if old else False
            files[path] = SourceFile(path, text, module_name, is_initializer, has_byte_order_mark)
        return Workspace(self.root, files.values())

    def file(self, path: str) -> SourceFile:
        normalized = self.relative_path(path)
        source_file = self.files.get(normalized)
        if source_file is None:
            raise RefusalError(RefusalCodes.FILE_NOT_FOUND, f"{path} is not a Python file of the workspace.")
        return source_file

    def relative_path(self, path: str | Path) -> str:
        """Normalizes a path given relative to the workspace root, or absolute, to the form used as a key."""
        candidate = Path(path)
        if candidate.is_absolute():
            try:
                candidate = candidate.resolve().relative_to(self.root)
            except ValueError:
                return str(path).replace("\\", "/")
        return candidate.as_posix()

    def edit(self, file: str, start_offset: int, end_offset: int, new_text: str) -> TextEdit:
        source_file = self.file(file)
        return TextEdit(
            source_file.path,
            source_file.position_of_offset(start_offset),
            source_file.position_of_offset(end_offset),
            new_text,
        )

    def apply_edits(self, edits: Sequence[TextEdit]) -> dict[str, str]:
        """Returns the new text of every file that the edits change; edits must not overlap."""
        spans_by_file = self.edit_spans(edits)
        return {path: apply_spans(self.files[path].text, spans) for path, spans in spans_by_file.items()}

    def edit_spans(self, edits: Sequence[TextEdit]) -> dict[str, list[EditSpan]]:
        spans_by_file: dict[str, list[EditSpan]] = {}
        for edit in edits:
            source_file = self.file(edit.file)
            spans_by_file.setdefault(source_file.path, []).append(
                EditSpan(
                    source_file.offset_of_position(edit.start),
                    source_file.offset_of_position(edit.end),
                    edit.new_text,
                )
            )
        return {path: sorted(spans, key=lambda s: (s.start_offset, s.end_offset)) for path, spans in spans_by_file.items()}

    def write_texts(self, texts: Mapping[str, str]) -> None:
        for path, text in texts.items():
            prefix = _UTF8_BYTE_ORDER_MARK if self.files[path].has_byte_order_mark else ""
            (self.root / path).write_bytes((prefix + text).encode("utf-8"))


def apply_spans(text: str, spans: Sequence[EditSpan]) -> str:
    ordered = sorted(spans, key=lambda span: (span.start_offset, span.end_offset))
    pieces = []
    cursor = 0
    for span in ordered:
        if span.start_offset < cursor:
            raise RefusalError(RefusalCodes.INTERNAL_VERIFICATION_FAILED, "The refactoring produced overlapping edits.")
        pieces.append(text[cursor : span.start_offset])
        pieces.append(span.new_text)
        cursor = span.end_offset
    pieces.append(text[cursor:])
    return "".join(pieces)
