"""Verification after transformation (the specification's principles.md, "Verification after transformation").

`verify_edits` checks, for a refactoring's edits:
  1. every edited file parses and `compile()`s;
  2. the re-binding check: every occurrence outside the edited regions, and every occurrence inside an edited
     region that the caller expects to be preserved, binds to the same symbol after the edits as before
     (accounting for `renamed_symbols`), and no new occurrence appears.
A failure raises `RefusalError` with the code `internal-verification-failed` (a bug in the refactoring).
"""

import warnings
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from riktigrefactor.protocol import RefusalCodes, RefusalError, SemanticModelError, TextEdit
from riktigrefactor.semantics import (
    Occurrence,
    OccurrenceRole,
    Symbol,
    SymbolKind,
    WorkspaceBindings,
    analyze_workspace,
)
from riktigrefactor.workspace import EditSpan, Workspace


def _verification_failed(message: str) -> RefusalError:
    return RefusalError(RefusalCodes.INTERNAL_VERIFICATION_FAILED, message)


class OffsetShifter:
    """Maps offsets in the text before edits to the text after them."""

    def __init__(self, spans: Sequence[EditSpan]) -> None:
        self.spans = sorted(spans, key=lambda span: (span.start_offset, span.end_offset))

    def shift(self, offset: int) -> int | None:
        """The offset after the edits, or None when the offset is inside or at the start of replaced text."""
        delta = 0
        for span in self.spans:
            if span.end_offset <= offset:
                delta += len(span.new_text) - (span.end_offset - span.start_offset)
            elif span.start_offset <= offset:
                return None
            else:
                break
        return offset + delta

    def touching_span_index(self, start_offset: int, end_offset: int) -> int | None:
        for index, span in enumerate(self.spans):
            replaced = span.start_offset < end_offset and start_offset < span.end_offset
            inserted_inside = span.start_offset == span.end_offset and start_offset < span.start_offset < end_offset
            if replaced or inserted_inside:
                return index
        return None

    def new_span_bounds(self, index: int) -> tuple[int, int]:
        delta = sum(len(s.new_text) - (s.end_offset - s.start_offset) for s in self.spans[:index])
        span = self.spans[index]
        new_start = span.start_offset + delta
        return new_start, new_start + len(span.new_text)


@dataclass(frozen=True)
class _Fingerprint:
    role: OccurrenceRole
    symbol: Symbol
    alternatives: tuple[Symbol, ...]
    origin: Symbol


class _Mapper:
    def __init__(
        self,
        before: WorkspaceBindings,
        shifters: Mapping[str, OffsetShifter],
        renamed_symbols: Mapping[Symbol, str],
        returned_imports: frozenset[Symbol] = frozenset(),
    ) -> None:
        self.returned_imports = returned_imports
        self.before = before
        self.shifters = shifters
        self.renamed_symbols = renamed_symbols
        self._symbol_before_by_symbol_after: dict[Symbol, Symbol] = {}

    def map_symbol(self, symbol: Symbol) -> Symbol | None:
        """The symbol as it should be after the edits; None when its scopes were rewritten by the edits.

        Raises when two different symbols would become the same one (a merge, such as a rename that collides).
        """
        mapped = self._map_symbol(symbol)
        if mapped is not None:
            other = self._symbol_before_by_symbol_after.setdefault(mapped, symbol)
            if other != symbol:
                raise _verification_failed(
                    f"{_describe(other)} and {_describe(symbol)} would be the same symbol after the edits."
                )
        return mapped

    def _map_symbol(self, symbol: Symbol) -> Symbol | None:
        scope = []
        if symbol.scope:
            module = self.before.modules[symbol.module]
            shifter = self.shifters.get(module.file.path)
            for key in symbol.scope:
                shifted = shifter.shift(key.start_offset) if shifter else key.start_offset
                if shifted is None:
                    return None
                scope.append(type(key)(key.kind, shifted))
        name = self.renamed_symbols.get(symbol, symbol.name)
        return Symbol(symbol.kind, symbol.module, tuple(scope), name)

    def _origin_before(self, symbol: Symbol) -> Symbol:
        """The origin of an import alias; a returned import (see `verify_edits`) is its own origin."""
        chain = self.before.alias_chain(symbol)
        for link in chain:
            if link in self.returned_imports:
                return link
        return chain[-1]

    def fingerprint(self, occurrence: Occurrence) -> _Fingerprint | None:
        symbol = self.map_symbol(occurrence.symbol)
        origin = self.map_symbol(self._origin_before(occurrence.symbol))
        alternatives = [self.map_symbol(alternative) for alternative in occurrence.alternatives]
        if symbol is None or origin is None or any(alternative is None for alternative in alternatives):
            return None
        return _Fingerprint(occurrence.role, symbol, tuple(a for a in alternatives if a is not None), origin)


def _fingerprint_of_new(after: WorkspaceBindings, occurrence: Occurrence) -> _Fingerprint:
    return _Fingerprint(
        occurrence.role,
        occurrence.symbol,
        occurrence.alternatives,
        after.origin_of(occurrence.symbol),
    )


def verify_edits(
    workspace: Workspace,
    edits: Sequence[TextEdit],
    *,
    renamed_symbols: Mapping[Symbol, str] | None = None,
    edited_regions_are_rewritten: bool = False,
    returned_imports: frozenset[Symbol] = frozenset(),
) -> Workspace:
    """Returns the workspace after the edits, or raises `RefusalError` (internal-verification-failed).

    `renamed_symbols` maps each symbol (as it is before the edits) that the refactoring renames to its new name.
    Occurrences touched by an edit are compared region by region: the multiset of (role, symbol, alternatives,
    origin) inside the replaced text must equal the one inside its replacement. With
    `edited_regions_are_rewritten=True` (for refactorings such as Extract IIFE that restructure the edited
    code) those regions, and symbols whose scopes start inside them, are not compared; the refactoring must check
    them itself. Occurrences outside the edited regions are always compared.
    `returned_imports` are import-bound symbols (as before the edits) that the refactoring turned into plain
    variables: they were bound by an import inside the edited text, which now returns the name, so they stop being
    import aliases. Any other change of an alias's origin is still a failure.
    """
    renamed_symbols = renamed_symbols or {}
    new_texts = workspace.apply_edits(edits)
    new_workspace = _reparse_and_compile(workspace, new_texts)
    try:
        before = analyze_workspace(workspace)
        after = analyze_workspace(new_workspace)
    except SemanticModelError as error:
        raise _verification_failed(f"The edited workspace cannot be analyzed: {error.message}") from error
    shifters = {path: OffsetShifter(spans) for path, spans in workspace.edit_spans(edits).items()}
    mapper = _Mapper(before, shifters, renamed_symbols, returned_imports)
    for path in workspace.files:
        _compare_file(path, before, after, shifters.get(path, OffsetShifter([])), mapper, edited_regions_are_rewritten)
    return new_workspace


def _reparse_and_compile(workspace: Workspace, new_texts: Mapping[str, str]) -> Workspace:
    try:
        new_workspace = workspace.with_texts(new_texts)
    except RefusalError as error:
        raise _verification_failed(f"The edited workspace does not parse: {error.message}") from error
    for path, text in new_texts.items():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                compile(text, path, "exec", dont_inherit=True)
        except (SyntaxError, ValueError, RecursionError) as error:
            raise _verification_failed(f"{path} does not compile after the edits: {error}") from error
    return new_workspace


def _compare_file(
    path: str,
    before: WorkspaceBindings,
    after: WorkspaceBindings,
    shifter: OffsetShifter,
    mapper: _Mapper,
    edited_regions_are_rewritten: bool,
) -> None:
    new_by_position: dict[tuple[int, OccurrenceRole], list[Occurrence]] = {}
    for occurrence in after.occurrences_in_file(path):
        new_by_position.setdefault((occurrence.start_offset, occurrence.role), []).append(occurrence)
    consumed: set[int] = set()
    old_in_region: dict[int, list[Occurrence]] = {}
    old_file = before.workspace.files[path]
    for old in before.occurrences_in_file(path):
        region = shifter.touching_span_index(old.start_offset, old.end_offset)
        if region is not None:
            old_in_region.setdefault(region, []).append(old)
            continue
        expected = mapper.fingerprint(old)
        new_start = shifter.shift(old.start_offset)
        if new_start is None:
            continue
        candidates = new_by_position.get((new_start, old.role), [])
        if expected is None:
            if not edited_regions_are_rewritten:
                raise _verification_failed(f"{path}: a scope of {old.source_name} was rewritten by the edits.")
            consumed.update(id(c) for c in candidates)
            continue
        if len(candidates) != 1:
            raise _verification_failed(
                f"{path}:{_line(old_file, old)}: {old.source_name} ({old.role.value}) has no counterpart after the edits."
            )
        consumed.add(id(candidates[0]))
        actual = _fingerprint_of_new(after, candidates[0])
        if actual != expected:
            raise _verification_failed(
                f"{path}:{_line(old_file, old)}: {old.source_name} ({old.role.value}) bound to "
                f"{_describe(expected.symbol)} before and binds to {_describe(actual.symbol)} after the edits."
            )
    if edited_regions_are_rewritten:
        return
    for region_index, old_occurrences in old_in_region.items():
        _compare_region(path, after, shifter, mapper, region_index, old_occurrences, consumed)
    for index, span in enumerate(shifter.spans):
        if index not in old_in_region:
            _compare_region(path, after, shifter, mapper, index, [], consumed)
    for new in after.occurrences_in_file(path):
        if id(new) not in consumed:
            raise _verification_failed(f"{path}: {new.source_name} ({new.role.value}) appeared outside the edited regions.")


def _compare_region(
    path: str,
    after: WorkspaceBindings,
    shifter: OffsetShifter,
    mapper: _Mapper,
    region_index: int,
    old_occurrences: list[Occurrence],
    consumed: set[int],
) -> None:
    new_start, new_end = shifter.new_span_bounds(region_index)
    new_occurrences = [
        o for o in after.occurrences_in_file(path) if new_start <= o.start_offset and o.end_offset <= new_end
    ]
    consumed.update(id(o) for o in new_occurrences)
    expected = Counter(mapper.fingerprint(o) for o in old_occurrences)
    actual = Counter(_fingerprint_of_new(after, o) for o in new_occurrences)
    if expected != actual:
        raise _verification_failed(
            f"{path}: the names inside the edit at offset {shifter.spans[region_index].start_offset} "
            "do not bind to the same symbols after the edit."
        )


def _line(file, occurrence: Occurrence) -> int:
    return file.position_of_offset(occurrence.start_offset).line


def _describe(symbol: Symbol) -> str:
    if symbol.kind is SymbolKind.BINDING:
        return f"{symbol.name} in {symbol.module}"
    return f"{symbol.kind.value} {symbol.name}"
