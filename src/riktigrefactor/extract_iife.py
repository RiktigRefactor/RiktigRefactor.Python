"""Extract IIFE, also called extract no-capture lambda (the specification's refactorings/extract-iife.md, Python section).

A selected expression becomes `(lambda a, b: <expr>)(a, b)`; selected whole statements become a nested
`def _extractedN(a, b): ...` immediately before `a, b = _extractedN(a, b)`.
The generated function captures nothing from enclosing function scopes: every local of an enclosing scope that the
selection uses is a parameter, and every local the selection writes and the rest of the function reads is returned and
assigned back. Module globals and builtins are looked up by name, so they are not passed. After the edit, the tool
checks with its own binding model and with CPython's `symtable` that the generated function has no free variables.

The tool refuses whenever it cannot prove that behavior is preserved; docs/extract-iife.md lists the reasons.
"""

import ast
import bisect
import builtins
import io
import re
import symtable
import tokenize
from collections.abc import Iterable
from dataclasses import dataclass, field

from riktigrefactor.protocol import (
    ExtractIifeRequest,
    RefusalCodes,
    RefusalError,
    Result,
    Success,
    returning_refusals,
)
from riktigrefactor.semantics import (
    ModuleBindings,
    Occurrence,
    OccurrenceRole,
    Scope,
    ScopeKind,
    Symbol,
    SymbolKind,
    WorkspaceBindings,
    analyze_workspace,
)
from riktigrefactor.verification import verify_edits
from riktigrefactor.workspace import SourceFile, Workspace


class Codes:
    """The refusal codes of Extract IIFE (see refusal-codes.md)."""

    UNSUPPORTED_POSITION = "unsupported-position"
    NON_LOCAL_CONTROL_FLOW = "non-local-control-flow"
    YIELD_IN_SELECTION = "yield-in-selection"
    AWAIT_IN_SELECTION = "await-in-selection"
    SUPER_OR_CLASS_CELL = "super-or-class-cell"
    DYNAMIC_SCOPE_ACCESS = "dynamic-scope-access"
    NONLOCAL_OR_GLOBAL_WRITE = "nonlocal-or-global-write"
    WALRUS_CROSSES_BOUNDARY = "walrus-crosses-boundary"
    DELETES_OUTER_VARIABLE = "deletes-outer-variable"
    EXPRESSION_IS_TARGET = "expression-is-assignment-target"
    POSSIBLY_UNBOUND_VARIABLE = "possibly-unbound-variable"
    WRITES_LOST_ON_EXCEPTION = "writes-lost-on-exception"
    CLOSURE_CAPTURES_VARIABLE = "closure-captures-variable"
    CLOSURE_OBSERVES_WRITTEN_VARIABLE = "closure-observes-written-variable"
    VARIABLE_WRITTEN_BY_CLOSURE = "variable-written-by-closure"
    DECLARATION_ESCAPES = "declaration-escapes"
    STATEMENTS_IN_CLASS_BODY = "statements-in-class-body"
    DOCSTRING_IN_SELECTION = "docstring-in-selection"
    MODULE_VARIABLE_VISIBLE_ELSEWHERE = "module-variable-visible-elsewhere"
    STAR_IMPORT_IN_SELECTION = "star-import-in-selection"
    DYNAMIC_CLASS_NAMESPACE = "dynamic-class-namespace"


_READ_ROLES = frozenset({OccurrenceRole.READ, OccurrenceRole.AUGMENTED_WRITE, OccurrenceRole.DELETE})
_WRITE_ROLES = frozenset(
    {
        OccurrenceRole.WRITE,
        OccurrenceRole.AUGMENTED_WRITE,
        OccurrenceRole.DEFINITION,
        OccurrenceRole.IMPORT_BINDING,
        OccurrenceRole.EXCEPT_NAME,
        OccurrenceRole.MATCH_CAPTURE,
    }
)
_WRITE_OR_DELETE_ROLES = _WRITE_ROLES | {OccurrenceRole.DELETE}
_DYNAMIC_BUILTINS_IN_SELECTION = frozenset({"eval", "exec", "locals", "vars", "globals", "dir"})
_DYNAMIC_BUILTINS_IN_FUNCTION = frozenset({"eval", "exec", "locals", "vars", "dir"})
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_COMPREHENSION_NODES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_CLOSURE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.GeneratorExp)
_LOOP_NODES = (ast.For, ast.AsyncFor, ast.While)
_TRY_LIKE_NODES = tuple(getattr(ast, name) for name in ("Try", "TryStar", "With", "AsyncWith") if hasattr(ast, name))
_OPAQUE_STRING_NODES = tuple(
    getattr(ast, name) for name in ("JoinedStr", "TemplateStr", "FormattedValue", "Interpolation") if hasattr(ast, name)
)
_TRIVIA = re.compile(r"(?:\s|#[^\r\n]*)*")
_INDENT_UNIT = "    "


def _is_trivia(text: str) -> bool:
    return _TRIVIA.fullmatch(text) is not None


# --------------------------------------------------------------------------------------------------------------------
# Locating the selection
# --------------------------------------------------------------------------------------------------------------------


@dataclass
class Selection:
    file: SourceFile
    parents: dict[int, ast.AST]
    start: int
    """Start offset of the selected expression, or of the first selected statement (including its decorators)."""
    end: int
    """End offset of the selected expression, or of the last selected statement."""
    expression: ast.expr | None
    statements: list[ast.stmt]

    @property
    def anchor(self) -> ast.AST:
        return self.expression if self.expression is not None else self.statements[0]


def _refuse(code: str, message: str, file: SourceFile | None = None, start: int = 0, end: int = 0) -> RefusalError:
    location = file.location_of_offsets(start, end) if file is not None else None
    return RefusalError(code, message, location)


def statement_start(file: SourceFile, statement: ast.stmt) -> int:
    start = file.start_offset(statement)
    for decorator in getattr(statement, "decorator_list", []):
        start = min(start, file.text.rfind("@", 0, file.start_offset(decorator)))
    return start


def parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _statement_blocks(tree: ast.AST) -> Iterable[list[ast.stmt]]:
    for node in ast.walk(tree):
        for _, value in ast.iter_fields(node):
            if isinstance(value, list) and value and all(isinstance(item, ast.stmt) for item in value):
                yield value


def _is_docstring_statement(statement: ast.stmt, parents: dict[int, ast.AST]) -> bool:
    if not (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    ):
        return False
    parent = parents.get(id(statement))
    return (
        isinstance(parent, (ast.Module, ast.ClassDef, *_FUNCTION_NODES))
        and bool(parent.body)
        and parent.body[0] is statement
    )


def _statement_fills_its_lines(file: SourceFile, statement: ast.stmt) -> bool:
    start = statement_start(file, statement)
    line_start = file.line_start_offset(file.position_of_offset(start).line)
    end = file.end_offset(statement)
    line_end = file.line_text_end_offset(file.position_of_offset(end).line)
    return file.text[line_start:start].strip() == "" and _is_trivia(file.text[end:line_end])


def locate_selection(request: ExtractIifeRequest, workspace: Workspace) -> Selection:
    """Finds the one expression or the whole statements that the request selects, or refuses."""
    file = workspace.file(request.file)
    text = file.text
    raw_start = file.offset_of_position(request.start)
    raw_end = file.offset_of_position(request.end)
    if raw_start > raw_end:
        raise _refuse(RefusalCodes.INVALID_SELECTION, "The selection ends before it starts.")
    start, end = raw_start, raw_end
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start == end:
        raise _refuse(RefusalCodes.INVALID_SELECTION, "The selection is empty.")
    parents = parent_map(file.tree)

    expression_by_span: dict[tuple[int, int], ast.expr] = {}
    for node in ast.walk(file.tree):
        if isinstance(node, ast.expr) and not isinstance(node, (ast.Slice, ast.Starred)):
            expression_by_span.setdefault((file.start_offset(node), file.end_offset(node)), node)
    expression = None
    expression_start, expression_end = start, end
    for _ in range(8):
        expression = expression_by_span.get((expression_start, expression_end))
        if expression is not None or not (text[expression_start] == "(" and text[expression_end - 1] == ")"):
            break
        expression_start += 1
        expression_end -= 1
        while expression_start < expression_end and text[expression_start].isspace():
            expression_start += 1
        while expression_end > expression_start and text[expression_end - 1].isspace():
            expression_end -= 1
        if expression_start >= expression_end:
            break

    statements = None
    for candidate in _statement_blocks(file.tree):
        first_index = bisect.bisect_left([statement_start(file, s) for s in candidate], raw_start)
        if first_index >= len(candidate):
            continue
        last_index = bisect.bisect_right([file.end_offset(s) for s in candidate], raw_end) - 1
        if last_index < first_index:
            continue
        if not _is_trivia(text[raw_start : statement_start(file, candidate[first_index])]):
            continue
        if not _is_trivia(text[file.end_offset(candidate[last_index]) : raw_end]):
            continue
        statements = candidate[first_index : last_index + 1]
        break

    if statements is not None:
        only = statements[0]
        single_expression_statement = len(statements) == 1 and isinstance(only, ast.Expr) and expression is only.value
        use_statements = not single_expression_statement or (
            _statement_fills_its_lines(file, only) and not isinstance(parents.get(id(only)), ast.ClassDef)
        )
        if use_statements:
            return Selection(
                file, parents, statement_start(file, statements[0]), file.end_offset(statements[-1]), None, statements
            )
    if expression is None:
        raise _refuse(
            RefusalCodes.INVALID_SELECTION,
            "The selection must be exactly one expression, or one or more whole statements of one block.",
            file,
            raw_start,
            raw_end,
        )
    return Selection(file, parents, file.start_offset(expression), file.end_offset(expression), expression, [])


# --------------------------------------------------------------------------------------------------------------------
# Scopes around the selection
# --------------------------------------------------------------------------------------------------------------------


def scope_node_of(parents: dict[int, ast.AST], node: ast.AST) -> ast.AST:
    """The node whose scope `node` is evaluated in; refuses positions where a lambda or def cannot be introduced."""
    child = node
    while True:
        parent = parents.get(id(child))
        if parent is None:
            return child
        if isinstance(parent, ast.pattern) or (_OPAQUE_STRING_NODES and isinstance(parent, _OPAQUE_STRING_NODES)):
            raise _refuse(
                Codes.UNSUPPORTED_POSITION,
                "The selection is inside a pattern or a formatted string, where it cannot be wrapped.",
            )
        if isinstance(parent, _FUNCTION_NODES):
            if getattr(parent, "type_params", None):
                raise _refuse(Codes.UNSUPPORTED_POSITION, "Functions with type parameters are not supported.")
            if any(child is statement for statement in parent.body):
                return parent
            if child is parent.returns:
                raise _refuse(Codes.UNSUPPORTED_POSITION, "The selection is inside an annotation.")
        elif isinstance(parent, ast.Lambda):
            if child is parent.body:
                return parent
        elif isinstance(parent, ast.ClassDef):
            if getattr(parent, "type_params", None):
                raise _refuse(Codes.UNSUPPORTED_POSITION, "Classes with type parameters are not supported.")
            if any(child is statement for statement in parent.body):
                return parent
        elif isinstance(parent, ast.arg):
            raise _refuse(Codes.UNSUPPORTED_POSITION, "The selection is inside an annotation.")
        elif isinstance(parent, ast.comprehension):
            comprehension = parents[id(parent)]
            first_iterable = child is parent.iter and comprehension.generators[0] is parent  # type: ignore[attr-defined]
            if not first_iterable:
                return comprehension
        elif isinstance(parent, _COMPREHENSION_NODES):
            if not isinstance(child, ast.comprehension):
                return parent
        elif isinstance(parent, ast.AnnAssign) and child is parent.annotation:
            raise _refuse(Codes.UNSUPPORTED_POSITION, "The selection is inside an annotation.")
        elif hasattr(ast, "TypeAlias") and isinstance(parent, ast.TypeAlias):
            raise _refuse(Codes.UNSUPPORTED_POSITION, "The selection is inside a type alias.")
        child = parent


def owner_node_of_statement(parents: dict[int, ast.AST], statement: ast.AST) -> ast.AST:
    node = parents.get(id(statement))
    while node is not None and not isinstance(node, (ast.Module, ast.ClassDef, *_FUNCTION_NODES)):
        node = parents.get(id(node))
    assert node is not None
    return node


# --------------------------------------------------------------------------------------------------------------------
# Definite assignment
# --------------------------------------------------------------------------------------------------------------------

State = frozenset[Symbol] | None
"""The symbols that are definitely assigned; None means the point is unreachable (everything holds vacuously)."""


def _meet(*states: State) -> State:
    reachable = [state for state in states if state is not None]
    if not reachable:
        return None
    result = reachable[0]
    for state in reachable[1:]:
        result = result & state
    return result


def _child_blocks(statement: ast.stmt) -> list[list[ast.stmt]]:
    blocks = []
    for name in ("body", "orelse", "finalbody"):
        value = getattr(statement, name, None)
        if isinstance(value, list):
            blocks.append(value)
    for handler in getattr(statement, "handlers", []):
        blocks.append(handler.body)
    for case in getattr(statement, "cases", []):
        blocks.append(case.body)
    return blocks


def _has_break(statements: list[ast.stmt]) -> bool:
    for statement in statements:
        if isinstance(statement, ast.Break):
            return True
        if isinstance(statement, (*_FUNCTION_NODES, ast.ClassDef)):
            continue
        if isinstance(statement, _LOOP_NODES):
            if _has_break(statement.orelse):
                return True
            continue
        if any(_has_break(block) for block in _child_blocks(statement)):
            return True
    return False


class OccurrenceIndex:
    def __init__(self, occurrences: list[Occurrence]) -> None:
        self.occurrences = occurrences
        self.starts = [occurrence.start_offset for occurrence in occurrences]

    def within(self, start: int, end: int) -> list[Occurrence]:
        found = []
        index = bisect.bisect_left(self.starts, start)
        while index < len(self.occurrences) and self.starts[index] < end:
            if self.occurrences[index].end_offset <= end:
                found.append(self.occurrences[index])
            index += 1
        return found


class _Flow:
    """A conservative definite-assignment analysis of the variables of one scope (an under-approximation).

    It records the reads that may happen before an assignment, and snapshots the state before chosen statements.
    """

    def __init__(self, file: SourceFile, module: ModuleBindings, index: OccurrenceIndex, owner_path: tuple) -> None:
        self.file = file
        self.module = module
        self.index = index
        self.owner_path = owner_path
        self.exposed: dict[Symbol, int] = {}
        self.snapshots: dict[int, State] = {}
        self.target_ids: set[int] = set()
        self.recording = True
        self.break_states: list[list[State]] = []
        """For each enclosing loop of the statement being analyzed, the states at its break statements."""

    def owned(self, occurrence: Occurrence) -> bool:
        symbol = occurrence.symbol
        return symbol.kind is SymbolKind.BINDING and symbol.scope == self.owner_path

    def _span(self, node: ast.AST) -> tuple[int, int]:
        if isinstance(node, ast.stmt):
            return statement_start(self.file, node), self.file.end_offset(node)
        return self.file.start_offset(node), self.file.end_offset(node)

    def reads(self, nodes: Iterable[ast.AST | None], state: State) -> None:
        if state is None or not self.recording:
            return
        for node in nodes:
            if node is None:
                continue
            start, end = self._span(node)
            for occurrence in self.index.within(start, end):
                if occurrence.role in _READ_ROLES and self.owned(occurrence) and occurrence.symbol not in state:
                    self.exposed.setdefault(occurrence.symbol, occurrence.start_offset)

    def _roles_in(self, node: ast.AST, roles: Iterable[OccurrenceRole]) -> set[Symbol]:
        start, end = self._span(node)
        wanted = set(roles)
        return {o.symbol for o in self.index.within(start, end) if o.role in wanted and self.owned(o)}

    def target_symbols(self, target: ast.AST) -> set[Symbol]:
        symbols: set[Symbol] = set()
        if isinstance(target, ast.Name):
            for occurrence in self.module.occurrences_of_node(target):
                if occurrence.role in _WRITE_ROLES and self.owned(occurrence):
                    symbols.add(occurrence.symbol)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                symbols |= self.target_symbols(element)
        elif isinstance(target, ast.Starred):
            symbols |= self.target_symbols(target.value)
        return symbols

    def deleted_in(self, statements: list[ast.stmt]) -> set[Symbol]:
        deleted: set[Symbol] = set()
        for statement in statements:
            deleted |= self._roles_in(statement, [OccurrenceRole.DELETE])
        return deleted

    def block(self, statements: list[ast.stmt], state: State) -> State:
        for statement in statements:
            if id(statement) in self.target_ids and id(statement) not in self.snapshots:
                self.snapshots[id(statement)] = state
            state = self.statement(statement, state)
        return state

    @staticmethod
    def _union(state: State, symbols: set[Symbol]) -> State:
        return None if state is None else state | symbols

    def statement(self, statement: ast.stmt, state: State) -> State:
        if isinstance(statement, ast.If):
            self.reads([statement.test], state)
            return _meet(self.block(statement.body, state), self.block(statement.orelse, state))
        if isinstance(statement, ast.While):
            self.reads([statement.test], state)
            return self._loop(statement, state, state)
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            self.reads([statement.iter, statement.target], state)
            return self._loop(statement, state, self._union(state, self.target_symbols(statement.target)))
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            targets: set[Symbol] = set()
            for item in statement.items:
                self.reads([item.context_expr, item.optional_vars], state)
                if item.optional_vars is not None:
                    targets |= self.target_symbols(item.optional_vars)
            inner = self._union(state, targets)
            self.block(statement.body, inner)
            return None if inner is None else inner - self.deleted_in(statement.body)
        if hasattr(statement, "handlers"):
            return self._try(statement, state)
        if hasattr(ast, "Match") and isinstance(statement, ast.Match):
            return self._match(statement, state)
        self.reads([statement], state)
        return self._simple(statement, state)

    def _loop(self, statement, state: State, body_state: State) -> State:
        self.break_states.append([])
        self.block(statement.body, body_state)
        states_at_break = self.break_states.pop()
        deleted = self.deleted_in(statement.body)
        after = None if state is None else state - deleted
        else_end = self.block(statement.orelse, after)
        if _has_break(statement.body):
            return _meet(else_end, *[None if at_break is None else at_break - deleted for at_break in states_at_break])
        return else_end

    def _try(self, statement, state: State) -> State:
        breaks_before = len(self.break_states[-1]) if self.break_states else 0
        body_end = self.block(statement.body, state)
        body_end = self.block(statement.orelse, body_end)
        handler_start = None if state is None else state - self.deleted_in(statement.body)
        ends = [body_end]
        for handler in statement.handlers:
            self.reads([handler.type], handler_start)
            name_symbols: set[Symbol] = set()
            if handler.name is not None:
                name_symbols = {
                    o.symbol
                    for o in self.index.within(self.file.start_offset(handler), self.file.start_offset(handler.body[0]))
                    if o.role is OccurrenceRole.EXCEPT_NAME and self.owned(o)
                }
            end = self.block(handler.body, self._union(handler_start, name_symbols))
            ends.append(None if end is None else end - name_symbols)
        after_try = _meet(*ends)
        if statement.finalbody and self.break_states:
            deleted_by_finally = self.deleted_in(statement.finalbody)
            recorded = self.break_states[-1]
            for index in range(breaks_before, len(recorded)):
                if recorded[index] is not None:
                    recorded[index] = recorded[index] - deleted_by_finally
        if statement.finalbody:
            unsafe = self.deleted_in(statement.body + statement.orelse + [s for h in statement.handlers for s in h.body])
            self.block(statement.finalbody, None if state is None else state - unsafe)
            recording, self.recording = self.recording, False
            try:
                return self.block(statement.finalbody, after_try)
            finally:
                self.recording = recording
        return after_try

    def _match(self, statement, state: State) -> State:
        self.reads([statement.subject], state)
        ends: list[State] = []
        exhaustive = False
        for case in statement.cases:
            self.reads([case.pattern, case.guard], state)
            captures = {
                o.symbol
                for o in self.index.within(*self._span(case.pattern))
                if o.role is OccurrenceRole.MATCH_CAPTURE and self.owned(o)
            }
            ends.append(self.block(case.body, self._union(state, captures)))
            if isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None and case.guard is None:
                exhaustive = True
        if not exhaustive:
            ends.append(state)
        return _meet(*ends)

    def _simple(self, statement: ast.stmt, state: State) -> State:
        if isinstance(statement, ast.Break):
            if state is not None and self.break_states:
                self.break_states[-1].append(state)
            return None
        if isinstance(statement, (ast.Return, ast.Raise, ast.Continue)):
            return None
        if state is None:
            return None
        if isinstance(statement, ast.Assign):
            written: set[Symbol] = set()
            for target in statement.targets:
                written |= self.target_symbols(target)
            return state | written
        if isinstance(statement, ast.AugAssign):
            return state | self.target_symbols(statement.target)
        if isinstance(statement, ast.AnnAssign):
            if statement.value is not None:
                return state | self.target_symbols(statement.target)
            return state
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            return state | self._roles_in(statement, [OccurrenceRole.IMPORT_BINDING])
        if isinstance(statement, (*_FUNCTION_NODES, ast.ClassDef)):
            defined = {
                o.symbol
                for o in self.module.occurrences_of_node(statement)
                if o.role is OccurrenceRole.DEFINITION and self.owned(o)
            }
            return state | defined
        if isinstance(statement, ast.Delete):
            return state - self._roles_in(statement, [OccurrenceRole.DELETE])
        return state


# --------------------------------------------------------------------------------------------------------------------
# The refactoring
# --------------------------------------------------------------------------------------------------------------------


def _fully_parenthesized(text: str) -> bool:
    if not (text.startswith("(") and text.endswith(")")):
        return False
    try:
        tokens = [
            token
            for token in tokenize.generate_tokens(io.StringIO(text).readline)
            if token.type not in (tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER, tokenize.COMMENT)
        ]
    except (tokenize.TokenError, SyntaxError):
        return False
    depth = 0
    for position, token in enumerate(tokens):
        if token.type == tokenize.OP and token.string in ("(", "[", "{"):
            depth += 1
        elif token.type == tokenize.OP and token.string in (")", "]", "}"):
            depth -= 1
            if depth == 0:
                return position == len(tokens) - 1
    return False


def _string_continuation_lines(text: str) -> set[int]:
    """1-based numbers of lines that begin inside a string token (their text must not be re-indented)."""
    lines: set[int] = set()
    fstring_middle = getattr(tokenize, "FSTRING_MIDDLE", None)
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.STRING or (fstring_middle is not None and token.type == fstring_middle):
                lines.update(range(token.start[0] + 1, token.end[0] + 1))
    except (tokenize.TokenError, SyntaxError):
        raise _refuse(RefusalCodes.FILE_NOT_PARSEABLE, "The file cannot be tokenized.") from None
    return lines


@dataclass
class _Plan:
    parameters: list[Symbol] = field(default_factory=list)
    returned: list[Symbol] = field(default_factory=list)


class _Extraction:
    def __init__(self, request: ExtractIifeRequest, workspace: Workspace) -> None:
        self.workspace = workspace
        self.selection = locate_selection(request, workspace)
        self.file = self.selection.file
        self.text = self.file.text
        self.parents = self.selection.parents
        self.start = self.selection.start
        self.end = self.selection.end
        self.region_end = self.end
        self.is_statements = self.selection.expression is None
        self.bindings: WorkspaceBindings = analyze_workspace(workspace)
        self.module: ModuleBindings = self.bindings.modules[self.file.module_key]
        self.index = OccurrenceIndex(self.module.occurrences)
        self.scope_by_path: dict[tuple, Scope] = {scope.path: scope for scope in self.module.scopes}
        self.state_cache: dict[int, State] = {}

    # ---- helpers ----

    def refuse(self, code: str, message: str) -> RefusalError:
        return _refuse(code, message, self.file, self.start, self.end)

    def inside(self, offset: int) -> bool:
        return self.start <= offset < self.end

    def spelling(self, symbol: Symbol) -> str:
        for occurrence in self.index.within(self.start, self.end):
            if occurrence.symbol == symbol:
                return occurrence.source_name
        return symbol.name

    @staticmethod
    def is_closure_between(occurrence_scope: Scope, owner: Scope) -> bool:
        """Whether code in `occurrence_scope` runs later than the code of `owner` that created it (through a function)."""
        scope: Scope | None = occurrence_scope
        while scope is not None and scope is not owner:
            if isinstance(scope.node, _CLOSURE_NODES):
                return True
            scope = scope.parent
        return False

    def is_closure_inside_selection(self, occurrence_scope: Scope) -> bool:
        return self.is_closure_between(occurrence_scope, self.scope)

    # ---- the whole refactoring ----

    def extract(self) -> Result:
        scope_node = scope_node_of(self.parents, self.selection.anchor)
        if self.is_statements:
            for statement in self.selection.statements:
                scope_node_of(self.parents, statement)
        scope = self.module.scope_of(scope_node)
        supported = (ScopeKind.MODULE, ScopeKind.FUNCTION, ScopeKind.LAMBDA, ScopeKind.CLASS, ScopeKind.COMPREHENSION)
        if scope is None or scope.kind not in supported:
            raise self.refuse(RefusalCodes.UNSUPPORTED_SCOPING, "The scope of the selection is not supported.")
        self.scope = scope
        self.scope_node = scope_node
        enclosing: Scope | None = scope
        while enclosing is not None:
            if enclosing.kind in (ScopeKind.TYPE_PARAMETERS, ScopeKind.ANNOTATION, ScopeKind.TYPE_ALIAS_VALUE):
                raise self.refuse(RefusalCodes.UNSUPPORTED_SCOPING, "Type parameter and annotation scopes are not supported.")
            enclosing = enclosing.parent
        if self.is_statements and scope.kind is ScopeKind.CLASS:
            raise self.refuse(
                Codes.STATEMENTS_IN_CLASS_BODY,
                "A function defined in a class body would become a method; select an expression instead.",
            )
        if scope.kind is ScopeKind.CLASS:
            self.check_class_namespace()
        self.check_docstring()
        self.check_not_a_target()
        self.check_callee_with_keywords()
        self.scan_structure()
        self.collect_ancestors()
        self.classify_occurrences()
        plan = self.plan()
        new_text, generated_offset, kind, name = self.generate(plan)
        return self.finish(new_text, generated_offset, kind, name, plan)

    # ---- structural preconditions ----

    def check_docstring(self) -> None:
        if self.is_statements:
            statements = self.selection.statements
        else:
            parent = self.parents.get(id(self.selection.expression))
            statements = [parent] if isinstance(parent, ast.Expr) else []
        for statement in statements:
            if _is_docstring_statement(statement, self.parents):
                raise self.refuse(Codes.DOCSTRING_IN_SELECTION, "The selection includes a docstring, which would stop being one.")

    def check_callee_with_keywords(self) -> None:
        parent = self.parents.get(id(self.selection.expression))
        if isinstance(parent, ast.Call) and parent.func is self.selection.expression and parent.keywords:
            raise self.refuse(
                Codes.UNSUPPORTED_POSITION,
                "The selection is the callee of a call with keyword arguments, which could no longer be matched to its parameters.",
            )

    def check_not_a_target(self) -> None:
        context = getattr(self.selection.expression, "ctx", None)
        if isinstance(context, (ast.Store, ast.Del)):
            raise self.refuse(Codes.EXPRESSION_IS_TARGET, "The expression is assigned to or deleted, so it is not a value.")

    def scan_structure(self) -> None:
        roots = self.selection.statements if self.is_statements else [self.selection.expression]
        for root in roots:
            self._scan(root, nested=False, loop_depth=0)
        selected = self.index.within(self.start, self.end)
        for occurrence in selected:
            symbol = occurrence.symbol
            if symbol.kind is SymbolKind.BUILTIN and symbol.name in _DYNAMIC_BUILTINS_IN_SELECTION:
                raise self.refuse(
                    Codes.DYNAMIC_SCOPE_ACCESS, f"The selection uses {symbol.name}, which observes or changes scopes by name."
                )
        if not self.is_statements:
            return
        if self.scope.kind is ScopeKind.MODULE:
            if self.module.dynamic_name_uses:
                raise self.refuse(
                    Codes.DYNAMIC_SCOPE_ACCESS, "The module uses names by spelling (star import, __all__, eval, globals, ...)."
                )
            return
        function_start = self.file.start_offset(self.scope_node)
        function_end = self.file.end_offset(self.scope_node)
        for occurrence in self.index.within(function_start, function_end):
            symbol = occurrence.symbol
            if symbol.kind is SymbolKind.BUILTIN and symbol.name in _DYNAMIC_BUILTINS_IN_FUNCTION:
                raise self.refuse(
                    Codes.DYNAMIC_SCOPE_ACCESS,
                    f"The enclosing function uses {symbol.name}, which could observe the new local function.",
                )

    def _scan(self, node: ast.AST, nested: bool, loop_depth: int) -> None:
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise self.refuse(Codes.NONLOCAL_OR_GLOBAL_WRITE, "The selection contains a global or nonlocal declaration.")
        if hasattr(ast, "TypeAlias") and isinstance(node, ast.TypeAlias):
            raise self.refuse(RefusalCodes.UNSUPPORTED_SCOPING, "The selection contains a type alias.")
        if getattr(node, "type_params", None):
            raise self.refuse(RefusalCodes.UNSUPPORTED_SCOPING, "The selection contains a definition with type parameters.")
        if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
            raise self.refuse(Codes.STAR_IMPORT_IN_SELECTION, "The selection contains a star import.")
        if isinstance(node, ast.ImportFrom) and node.module == "__future__" and node.level == 0:
            raise self.refuse(Codes.DECLARATION_ESCAPES, "A __future__ import must stay at the top of the module.")
        if isinstance(node, ast.AnnAssign) and not nested and self.scope.kind in (ScopeKind.MODULE, ScopeKind.CLASS):
            raise self.refuse(
                Codes.DECLARATION_ESCAPES,
                "An annotated assignment at module or class level records its annotation in __annotations__, "
                "which a function would not.",
            )
        if isinstance(node, ast.Name) and node.id == "__class__":
            raise self.refuse(Codes.SUPER_OR_CLASS_CELL, "The selection uses __class__.")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "super":
            if not node.args and not node.keywords:
                raise self.refuse(Codes.SUPER_OR_CLASS_CELL, "The selection uses zero-argument super(), which depends on its function.")
        if not nested:
            if isinstance(node, ast.Return):
                raise self.refuse(Codes.NON_LOCAL_CONTROL_FLOW, "The selection contains return.")
            if isinstance(node, (ast.Break, ast.Continue)) and loop_depth == 0:
                raise self.refuse(Codes.NON_LOCAL_CONTROL_FLOW, "The selection contains break or continue that leaves it.")
            if isinstance(node, (ast.Yield, ast.YieldFrom)):
                raise self.refuse(Codes.YIELD_IN_SELECTION, "The selection contains yield.")
            is_async_comprehension = isinstance(node, ast.comprehension) and node.is_async
            if isinstance(node, (ast.Await, ast.AsyncFor, ast.AsyncWith)) or is_async_comprehension:
                raise self.refuse(Codes.AWAIT_IN_SELECTION, "The selection contains await or an async construct.")
        if isinstance(node, (*_FUNCTION_NODES, ast.Lambda)):
            arguments = node.args
            header = [] if isinstance(node, ast.Lambda) else [*node.decorator_list]
            header += [*arguments.defaults, *[default for default in arguments.kw_defaults if default is not None]]
            for child in header:
                self._scan(child, nested, loop_depth)
            for child in node.body if isinstance(node.body, list) else [node.body]:
                self._scan(child, True, 0)
            return
        if isinstance(node, ast.ClassDef):
            for child in [*node.decorator_list, *node.bases, *[keyword.value for keyword in node.keywords]]:
                self._scan(child, nested, loop_depth)
            for child in node.body:
                self._scan(child, True, 0)
            return
        if isinstance(node, _LOOP_NODES):
            for child in ast.iter_child_nodes(node):
                in_else = any(child is statement for statement in node.orelse)
                self._scan(child, nested, loop_depth if in_else else loop_depth + 1)
            return
        for child in ast.iter_child_nodes(node):
            self._scan(child, nested, loop_depth)

    # ---- the context of the selection ----

    def collect_ancestors(self) -> None:
        self.ancestor_statements: list[ast.stmt] = []
        self.loop_spans: list[tuple[int, int]] = []
        self.try_like_ancestor = False
        self.guard_captures: set[Symbol] = set()
        self.walrus_bound_before: set[Symbol] = set()
        if self.is_statements:
            self.ancestor_statements.append(self.selection.statements[0])
        else:
            self.collect_walrus_bound_before()
        child: ast.AST = self.selection.anchor
        node: ast.AST | None = self.parents.get(id(child))
        within_scope = True
        while node is not None:
            if node is self.scope_node:
                within_scope = False
            if isinstance(node, ast.stmt):
                self.ancestor_statements.append(node)
            if within_scope and isinstance(node, _LOOP_NODES):
                self.loop_spans.append((statement_start(self.file, node), self.file.end_offset(node)))
            if within_scope and isinstance(node, _TRY_LIKE_NODES) and self.observes_lost_writes(node, child):
                self.try_like_ancestor = True
            if hasattr(ast, "match_case") and isinstance(node, ast.match_case) and child is node.guard:
                span = (self.file.start_offset(node.pattern), self.file.end_offset(node.pattern))
                self.guard_captures |= {
                    o.symbol for o in self.index.within(*span) if o.role is OccurrenceRole.MATCH_CAPTURE
                }
            child = node
            node = self.parents.get(id(node))

    @staticmethod
    def observes_lost_writes(node: ast.AST, child: ast.AST) -> bool:
        """Whether code of this try or with, other than the child that holds the selection, runs after an exception."""
        if not isinstance(node, (ast.Try, *([ast.TryStar] if hasattr(ast, "TryStar") else []))):
            return True  # a context manager can swallow the exception
        if any(child is statement for statement in node.body):
            return True  # an except clause or the finally clause runs
        if any(child is statement for statement in node.finalbody):
            return False
        return bool(node.finalbody)  # in a handler or the else clause, only the finally clause runs

    def collect_walrus_bound_before(self) -> None:
        """Variables that an operand evaluated before the selection, in the same statement, always assigns with :=."""
        child: ast.AST = self.selection.anchor
        node = self.parents.get(id(child))
        while node is not None and not isinstance(node, ast.stmt):
            for earlier in self.operands_evaluated_before(node, child):
                value = earlier.value if isinstance(earlier, (ast.keyword, ast.Starred)) else earlier
                if isinstance(value, ast.NamedExpr):
                    for occurrence in self.module.occurrences_of_node(value.target):
                        if occurrence.role in _WRITE_ROLES:
                            self.walrus_bound_before.add(occurrence.symbol)
            child = node
            node = self.parents.get(id(node))

    def operands_evaluated_before(self, node: ast.AST, child: ast.AST) -> list[ast.AST]:
        operands: list[ast.AST]
        if isinstance(node, ast.Call):
            operands = [node.func, *node.args, *node.keywords]
        elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            operands = list(node.elts)
        elif isinstance(node, ast.BinOp):
            operands = [node.left, node.right]
        elif isinstance(node, ast.Subscript):
            operands = [node.value, node.slice]
        elif isinstance(node, ast.Dict):
            operands = [item for item in [*node.keys, *node.values] if item is not None]
        else:
            return []
        operands.sort(key=self.file.start_offset)
        for index, operand in enumerate(operands):
            if operand is child:
                return operands[:index]
        return []

    def in_enclosing_loop(self, offset: int) -> bool:
        return any(start <= offset < end for start, end in self.loop_spans)

    # ---- variables crossing the boundary ----

    def crossing(self, symbol: Symbol) -> bool:
        return any(not self.inside(o.start_offset) for o in self.bindings.occurrences_of(symbol))

    def classify_occurrences(self) -> None:
        scope_path = self.scope.path
        is_module = self.scope.kind is ScopeKind.MODULE
        self.first_seen: dict[Symbol, int] = {}
        self.reads: dict[Symbol, int] = {}
        self.writes: dict[Symbol, int] = {}
        for occurrence in self.index.within(self.start, self.end):
            if occurrence.role not in _READ_ROLES and occurrence.role not in _WRITE_ROLES:
                continue
            symbol = occurrence.symbol
            if symbol.kind is not SymbolKind.BINDING or symbol.module != self.file.module_key:
                continue
            owner_path = symbol.scope
            if len(owner_path) > len(scope_path) or scope_path[: len(owner_path)] != owner_path:
                continue  # owned by a scope inside the selection
            if not owner_path and not is_module:
                if occurrence.role in _WRITE_OR_DELETE_ROLES:
                    raise self.refuse(
                        Codes.NONLOCAL_OR_GLOBAL_WRITE, f"The selection assigns {occurrence.source_name}, a module global here."
                    )
                continue
            module_global = is_module and not owner_path
            if module_global:
                if occurrence.role is OccurrenceRole.DELETE:
                    raise self.refuse(
                        Codes.DELETES_OUTER_VARIABLE, f"The selection deletes {occurrence.source_name}, a module attribute."
                    )
                if self.is_ephemeral_module_name(symbol):
                    continue
            if not self.crossing(symbol) and not (module_global and occurrence.role in _WRITE_ROLES):
                continue
            owner = self.scope_by_path.get(owner_path)
            if owner is None or not self._owner_supported(owner):
                raise self.refuse(RefusalCodes.UNSUPPORTED_SCOPING, f"The scope that owns {occurrence.source_name} is not supported.")
            if occurrence.role is OccurrenceRole.DELETE:
                raise self.refuse(Codes.DELETES_OUTER_VARIABLE, f"The selection deletes {occurrence.source_name}.")
            if occurrence.role in _WRITE_ROLES:
                if owner_path != scope_path:
                    raise self.refuse(
                        Codes.NONLOCAL_OR_GLOBAL_WRITE,
                        f"The selection assigns {occurrence.source_name}, a variable of an enclosing function.",
                    )
                if not self.is_statements:
                    raise self.refuse(
                        Codes.WALRUS_CROSSES_BOUNDARY, f"The expression assigns {occurrence.source_name}, which a lambda cannot do."
                    )
                self.writes.setdefault(symbol, occurrence.start_offset)
            if occurrence.role in _READ_ROLES:
                self.reads.setdefault(symbol, occurrence.start_offset)
            self.first_seen.setdefault(symbol, occurrence.start_offset)
        if is_module:
            self.reads = {s: offset for s, offset in self.reads.items() if s.scope or s in self.writes}

    def is_ephemeral_module_name(self, symbol: Symbol) -> bool:
        """A name that only an except clause of the selection binds and that nothing else uses: it is gone afterwards."""
        occurrences = self.bindings.occurrences_of(symbol)
        return all(self.inside(o.start_offset) for o in occurrences) and all(
            o.role is OccurrenceRole.EXCEPT_NAME for o in occurrences if o.role in _WRITE_ROLES
        )

    def _owner_supported(self, owner: Scope) -> bool:
        if owner.kind in (ScopeKind.FUNCTION, ScopeKind.LAMBDA, ScopeKind.COMPREHENSION):
            return True
        return owner.kind in (ScopeKind.CLASS, ScopeKind.MODULE) and owner is self.scope

    # ---- definite assignment before the selection ----

    def state_before(self, owner: Scope) -> State:
        key = id(owner)
        if key in self.state_cache:
            return self.state_cache[key]
        node = owner.node
        initial = frozenset(
            o.symbol
            for o in self.module.occurrences
            if o.role is OccurrenceRole.PARAMETER and o.symbol.scope == owner.path and o.symbol.kind is SymbolKind.BINDING
        )
        anchor_statement = None
        for statement in self.ancestor_statements:
            if owner_node_of_statement(self.parents, statement) is node:
                anchor_statement = statement
                break
        body = node.body if isinstance(node, (ast.Module, ast.ClassDef, *_FUNCTION_NODES)) else []
        result: State = initial
        if anchor_statement is not None:
            flow = _Flow(self.file, self.module, self.index, owner.path)
            flow.target_ids = {id(anchor_statement)}
            flow.block(body, initial)
            result = flow.snapshots.get(id(anchor_statement), frozenset())
        self.state_cache[key] = result
        return result

    def bound_before(self, symbol: Symbol) -> bool:
        if symbol in self.guard_captures or symbol in self.walrus_bound_before:
            return True
        owner = self.scope_by_path[symbol.scope]
        if owner.kind is ScopeKind.COMPREHENSION:
            return self._comprehension_variable_bound(symbol, owner)
        if owner is not self.scope:
            if any(o.role is OccurrenceRole.DELETE for o in self.bindings.occurrences_of(symbol)):
                return False
        state = self.state_before(owner)
        return state is None or symbol in state

    def _comprehension_variable_bound(self, symbol: Symbol, owner: Scope) -> bool:
        node = owner.node
        elements = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]  # type: ignore[attr-defined]
        for element in elements:
            if self.file.start_offset(element) <= self.start and self.end <= self.file.end_offset(element):
                return True
        target_ends = []
        for occurrence in self.bindings.occurrences_of(symbol):
            if occurrence.role not in _WRITE_ROLES:
                continue
            for generator in node.generators:  # type: ignore[attr-defined]
                if self.file.start_offset(generator.target) <= occurrence.start_offset < self.file.end_offset(generator.target):
                    target_ends.append(self.file.end_offset(generator.target))
                    break
            else:
                return False
        return all(end <= self.start for end in target_ends)

    # ---- the plan ----

    def live_after(self, symbol: Symbol) -> bool:
        owner = self.scope_by_path[symbol.scope]
        for occurrence in self.bindings.occurrences_of(symbol):
            if self.inside(occurrence.start_offset) or occurrence.role not in _READ_ROLES:
                continue
            if occurrence.start_offset >= self.end or self.in_enclosing_loop(occurrence.start_offset):
                return True
            if self.is_closure_between(occurrence.scope, owner):
                return True
        return False

    def is_stable(self, symbol: Symbol) -> bool:
        """The variable is assigned at most once, before the selection, and not inside a loop that holds both."""
        owner = self.scope_by_path[symbol.scope]
        occurrences = self.bindings.occurrences_of(symbol)
        writes = [o for o in occurrences if o.role in _WRITE_ROLES]
        if len(writes) > 1:
            return False
        if any(o.role is OccurrenceRole.DELETE for o in occurrences):
            return False
        if any(o.role is OccurrenceRole.EXCEPT_NAME for o in writes):
            return False  # the end of the except clause unbinds the name
        if not writes:
            return True
        write = writes[0]
        if write.start_offset >= self.start or self.is_closure_between(write.scope, owner):
            return False
        for node in ast.walk(self.file.tree):
            if isinstance(node, _LOOP_NODES):
                start, end = statement_start(self.file, node), self.file.end_offset(node)
                if start <= write.start_offset < end and start <= self.start < end:
                    return False
        return True

    def plan(self) -> _Plan:
        module_level = self.is_statements and self.scope.kind is ScopeKind.MODULE
        if module_level:
            self.check_module_variables(set(self.writes))
        tracked = set(self.reads) | set(self.writes)
        for symbol in tracked:
            owner = self.scope_by_path[symbol.scope]
            for occurrence in self.bindings.occurrences_of(symbol):
                if occurrence.role in _WRITE_OR_DELETE_ROLES and self.is_closure_between(occurrence.scope, owner):
                    raise self.refuse(
                        Codes.VARIABLE_WRITTEN_BY_CLOSURE,
                        f"{self.spelling(symbol)} is assigned by a nested function, so reading it earlier could see an old value.",
                    )
        for occurrence in self.index.within(self.start, self.end):
            symbol = occurrence.symbol
            if occurrence.role in _READ_ROLES and symbol in tracked:
                if self.is_closure_inside_selection(occurrence.scope) and not self.is_stable(symbol):
                    raise self.refuse(
                        Codes.CLOSURE_CAPTURES_VARIABLE,
                        f"A function created in the selection uses {occurrence.source_name}, which changes, so a copy could go stale.",
                    )
        plan = _Plan()
        exposed: set[Symbol] = set()
        must_assign: frozenset[Symbol] = frozenset()
        if self.is_statements:
            flow = _Flow(self.file, self.module, self.index, self.scope.path)
            end_state = flow.block(self.selection.statements, frozenset())
            exposed = set(flow.exposed)
            must_assign = frozenset(self.writes) if end_state is None else end_state
            for symbol in self.writes:
                if module_level or self.live_after(symbol):
                    self.check_returnable(symbol)
                    plan.returned.append(symbol)
            if plan.returned and self.try_like_ancestor and self.writes_can_be_lost():
                raise self.refuse(
                    Codes.WRITES_LOST_ON_EXCEPTION,
                    "An exception raised in the selection after it assigned a variable would lose that assignment, "
                    "which a try or with block could observe.",
                )
        needed: set[Symbol] = set()
        for symbol in self.reads:
            if symbol.scope != self.scope.path or not self.is_statements or symbol in exposed:
                needed.add(symbol)
        for symbol in plan.returned:
            if symbol not in must_assign:
                needed.add(symbol)
        for symbol in sorted(needed, key=lambda s: self.first_seen.get(s, 0)):
            if not self.bound_before(symbol) and not self.free_variable_read_is_equivalent(symbol):
                raise self.refuse(
                    Codes.POSSIBLY_UNBOUND_VARIABLE,
                    f"{self.spelling(symbol)} might not be assigned when the selection runs, and passing it would fail earlier.",
                )
            plan.parameters.append(symbol)
        if module_level:
            plan.returned.sort(key=lambda s: self.writes[s])
        else:
            plan.returned.sort(key=lambda s: self.first_seen.get(s, 0))
        return plan

    # ---- what the selection can do while it runs ----

    @staticmethod
    def _is_flat_name_target(target: ast.AST, allow_starred: bool) -> bool:
        if isinstance(target, ast.Name):
            return True
        if isinstance(target, (ast.Tuple, ast.List)):
            return all(
                isinstance(element, ast.Name) or (allow_starred and isinstance(element, ast.Starred) and isinstance(element.value, ast.Name))
                for element in target.elts
            )
        return False

    def writes_can_be_lost(self) -> bool:
        """Whether an exception could leave the selection after it assigned a variable that is returned.

        Not when the first statement that assigns such a variable is the last statement and its assignment is the last
        step: Python evaluates the value, unpacks it, and only then stores into plain names, and a single-name import
        binds the name after it has imported.
        """
        statements = self.selection.statements
        returned = {s for s in self.writes if self.live_after(s) or self.scope.kind is ScopeKind.MODULE}
        for index, statement in enumerate(statements):
            start, end = statement_start(self.file, statement), self.file.end_offset(statement)
            if any(o.symbol in returned and o.role in _WRITE_ROLES for o in self.index.within(start, end)):
                return not (index == len(statements) - 1 and self._assignment_is_last_step(statement))
        return False

    def _assignment_is_last_step(self, statement: ast.stmt) -> bool:
        def has_walrus(node: ast.AST | None) -> bool:
            return node is not None and any(isinstance(n, ast.NamedExpr) for n in ast.walk(node))

        if isinstance(statement, ast.Assign):
            return all(self._is_flat_name_target(t, True) for t in statement.targets) and not has_walrus(statement.value)
        if isinstance(statement, ast.AugAssign):
            return isinstance(statement.target, ast.Name) and not has_walrus(statement.value)
        if isinstance(statement, ast.AnnAssign):
            return isinstance(statement.target, ast.Name) and statement.value is not None and not has_walrus(statement.value)
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            return len(statement.names) == 1
        return False

    def cannot_run_code(self) -> bool:
        """Whether the statements only copy names and constants into plain names, so no other code runs meanwhile."""

        def is_plain_value(node: ast.AST) -> bool:
            if isinstance(node, ast.Constant):
                return True
            if isinstance(node, ast.Name):
                return isinstance(node.ctx, ast.Load)
            if isinstance(node, (ast.Tuple, ast.List)):
                return isinstance(node.ctx, ast.Load) and all(is_plain_value(e) for e in node.elts)
            return False

        for statement in self.selection.statements:
            if isinstance(statement, ast.Assign):
                for target in statement.targets:
                    if not self._is_flat_name_target(target, False):
                        return False
                    if not isinstance(target, ast.Name) and not isinstance(statement.value, (ast.Tuple, ast.List)):
                        return False  # unpacking iterates the value
                if not is_plain_value(statement.value):
                    return False
            elif isinstance(statement, ast.AnnAssign):
                if not isinstance(statement.target, ast.Name) or not (
                    statement.value is None or is_plain_value(statement.value)
                ):
                    return False
            else:
                return False
        return True

    def free_variable_read_is_equivalent(self, symbol: Symbol) -> bool:
        """A free variable of an enclosing function, assigned only after the selection's function was defined.

        Passing it reads it before the expression runs instead of while it runs. That is the same when the
        expression is a straight line of reads and operators (nothing before the read can run other code or fail
        differently), the variable is read unconditionally, and no other code can assign it in between.
        """
        if self.is_statements:
            return False
        owner = self.scope_by_path[symbol.scope]
        if owner is self.scope or owner.kind not in (ScopeKind.FUNCTION, ScopeKind.LAMBDA):
            return False
        suspends = (ast.Yield, ast.YieldFrom, ast.Await, ast.AsyncFor, ast.AsyncWith)
        if any(isinstance(n, suspends) for n in ast.walk(owner.node)):
            return False
        allowed = (ast.Constant, ast.BinOp, ast.UnaryOp, ast.Tuple, ast.List, ast.operator, ast.unaryop, ast.cmpop, ast.expr_context)
        for node in ast.walk(self.selection.expression):
            if isinstance(node, ast.Name):
                if not self._read_cannot_fail_differently(node):
                    return False
            elif isinstance(node, ast.Compare):
                if len(node.ops) != 1:
                    return False
            elif not isinstance(node, allowed):
                return False
        return True

    def _read_cannot_fail_differently(self, name: ast.Name) -> bool:
        for occurrence in self.module.occurrences_of_node(name):
            if occurrence.alternatives:
                return False
            symbol = occurrence.symbol
            if symbol.kind is SymbolKind.BUILTIN:
                return True
            if symbol.kind is not SymbolKind.BINDING or not symbol.scope or symbol.module != self.file.module_key:
                return False
            owner = self.scope_by_path[symbol.scope]
            if owner is not self.scope and owner.kind in (ScopeKind.FUNCTION, ScopeKind.LAMBDA):
                return True
            return self.bound_before(symbol)
        return False

    # ---- class bodies ----

    def check_class_namespace(self) -> None:
        """An expression in a class body reads the class namespace, which only a plain class keeps to the names we see."""
        class_node = self.scope_node
        assert isinstance(class_node, ast.ClassDef)
        for node in ast.walk(self.selection.anchor):
            if isinstance(node, ast.Name) and node.id in ("__qualname__", "__module__"):
                raise self.refuse(
                    Codes.DYNAMIC_CLASS_NAMESPACE,
                    f"{node.id} is an implicit name of the class body, which a lambda cannot see.",
                )
        start, end = self.file.start_offset(class_node), self.file.end_offset(class_node)
        for occurrence in self.index.within(start, end):
            symbol = occurrence.symbol
            if symbol.kind is SymbolKind.BUILTIN and symbol.name in _DYNAMIC_BUILTINS_IN_FUNCTION:
                raise self.refuse(
                    Codes.DYNAMIC_CLASS_NAMESPACE,
                    f"The class body uses {symbol.name}, so names may be in its namespace that the analysis cannot see.",
                )
        if not self.class_has_plain_namespace(class_node, set()):
            raise self.refuse(
                Codes.DYNAMIC_CLASS_NAMESPACE,
                "The class has a keyword (such as metaclass) or a base that is not a builtin or a plain class of this "
                "file, so a metaclass could give the class body a namespace with names the analysis cannot see.",
            )

    def class_has_plain_namespace(self, class_node: ast.ClassDef, seen: set[int]) -> bool:
        if id(class_node) in seen or class_node.keywords:
            return False
        seen.add(id(class_node))
        for base in class_node.bases:
            if not isinstance(base, ast.Name):
                return False
            occurrences = self.module.occurrences_of_node(base)
            if not occurrences or occurrences[0].alternatives:
                return False
            symbol = occurrences[0].symbol
            if symbol.kind is SymbolKind.BUILTIN:
                if not isinstance(getattr(builtins, symbol.name, None), type):
                    return False
            elif symbol.kind is SymbolKind.BINDING and symbol.module == self.file.module_key:
                bindings = [o for o in self.bindings.occurrences_of(symbol) if o.role in _WRITE_OR_DELETE_ROLES]
                if len(bindings) != 1 or bindings[0].role is not OccurrenceRole.DEFINITION:
                    return False
                definition = bindings[0].node
                if not isinstance(definition, ast.ClassDef) or not self.class_has_plain_namespace(definition, seen):
                    return False
            else:
                return False
        return True

    def check_returnable(self, symbol: Symbol) -> None:
        owner = self.scope_by_path[symbol.scope]
        for occurrence in self.index.within(self.start, self.end):
            if occurrence.symbol == symbol and occurrence.role is OccurrenceRole.DEFINITION:
                raise self.refuse(
                    Codes.DECLARATION_ESCAPES,
                    f"{occurrence.source_name} is defined in the selection and used after it (or is a module attribute); "
                    "its qualified name would change.",
                )
        if self.cannot_run_code():
            return
        for occurrence in self.bindings.occurrences_of(symbol):
            if self.inside(occurrence.start_offset) or not self.is_closure_between(occurrence.scope, owner):
                continue
            if occurrence.start_offset < self.end or self.in_enclosing_loop(occurrence.start_offset):
                raise self.refuse(
                    Codes.CLOSURE_OBSERVES_WRITTEN_VARIABLE,
                    f"A function outside the selection uses {self.spelling(symbol)}, which the selection assigns; it could run in between.",
                )

    def check_module_variables(self, symbols: set[Symbol]) -> None:
        """Module variables are module attributes: code that runs during the selection could see them change later."""
        if self.cannot_run_code():
            return
        for symbol in symbols:
            if symbol.scope:
                continue
            for occurrence in self.bindings.occurrences:
                uses_symbol = any(
                    symbol in self.bindings.alias_chain(candidate) for candidate in (occurrence.symbol, *occurrence.alternatives)
                )
                if uses_symbol and (occurrence.file != self.file.path or occurrence.scope is not self.module.root_scope):
                    raise self.refuse(
                        Codes.MODULE_VARIABLE_VISIBLE_ELSEWHERE,
                        f"{symbol.name} is also used by functions or other modules, which would see it change in a different order.",
                    )

    # ---- generating the text ----

    def unused_name(self) -> str:
        texts = [self.text]
        if self.scope.kind is ScopeKind.MODULE:
            texts = [file.text for file in self.workspace.files.values()]
        number = 1
        while any(re.search(rf"(?<!\w)_extracted{number}(?!\w)", text) for text in texts):
            number += 1
        return f"_extracted{number}"

    def generate(self, plan: _Plan) -> tuple[str, int, str, str]:
        """Returns the new text, the offset of the generated function in it, its kind, and its name."""
        names = [self.spelling(symbol) for symbol in plan.parameters]
        arguments = ", ".join(names)
        if not self.is_statements:
            expression = self.selection.expression
            body = self.text[self.start : self.end]
            if isinstance(expression, ast.Tuple) and not _fully_parenthesized(body):
                body = f"({body})"
            parameter_text = f" {arguments}" if arguments else ""
            call = f"(lambda{parameter_text}: {body})({arguments})"
            offset = 1
            parent = self.parents.get(id(expression))
            sole_generator_argument = (
                isinstance(expression, ast.GeneratorExp)
                and isinstance(parent, ast.Call)
                and len(parent.args) == 1
                and not parent.keywords
                and parent.args[0] is expression
            )
            if sole_generator_argument:
                call = f"({call})"
                offset = 2
            return call, offset, "lambda", "lambda"
        name = self.unused_name()
        last = self.selection.statements[-1]
        first_line = self.file.position_of_offset(self.start).line
        prefix = self.text[self.file.line_start_offset(first_line) : self.start]
        if prefix.strip() != "":
            raise self.refuse(RefusalCodes.INVALID_SELECTION, "The first selected statement does not start its line.")
        last_end = self.file.end_offset(last)
        last_line_end = self.file.line_text_end_offset(self.file.position_of_offset(last_end).line)
        rest = self.text[last_end:last_line_end]
        if rest.strip() == "":
            self.region_end = last_end
        elif rest.lstrip().startswith("#"):
            self.region_end = last_line_end
            while self.text[self.region_end - 1] in " \t":
                self.region_end -= 1
        else:
            raise self.refuse(RefusalCodes.INVALID_SELECTION, "Another statement follows the selection on its last line.")
        region = self.text[self.start : self.region_end]
        newline = "\r\n" if "\r\n" in self.text else "\n"
        continuation_lines = _string_continuation_lines(self.text)
        unit = "\t" if "\t" in prefix else _INDENT_UNIT
        pieces = []
        for index, line in enumerate(region.splitlines(keepends=True)):
            content = line.rstrip("\r\n")
            ending = line[len(content) :]
            if index == 0:
                pieces.append(prefix + unit + content + ending)
            elif content.strip() == "" or first_line + index in continuation_lines:
                pieces.append(line)
            else:
                pieces.append(("\t" if content.startswith("\t") else unit) + content + ending)
        returned = ", ".join(self.spelling(symbol) for symbol in plan.returned)
        header = f"def {name}({arguments}):{newline}"
        tail = ""
        if plan.returned:
            tail += f"{newline}{prefix}{unit}return {returned}"
        call = f"{name}({arguments})"
        if plan.returned:
            call = f"{returned} = {call}"
        tail += f"{newline}{prefix}{call}"
        return header + "".join(pieces) + tail, 0, "def", name

    # ---- verification and result ----

    def finish(self, new_text: str, generated_offset: int, kind: str, name: str, plan: _Plan) -> Result:
        edit = self.workspace.edit(self.file.path, self.start, self.region_end, new_text)
        returned_imports = frozenset(
            o.symbol
            for o in self.index.within(self.start, self.end)
            if o.role is OccurrenceRole.IMPORT_BINDING and o.symbol in plan.returned
        )
        new_workspace = verify_edits(
            self.workspace, [edit], edited_regions_are_rewritten=True, returned_imports=returned_imports
        )
        self.verify_no_captures(new_workspace, self.start + generated_offset, kind, name, plan)
        return Success(self.workspace.root_text, (edit,))

    @staticmethod
    def _verification_failed(message: str) -> RefusalError:
        return RefusalError(RefusalCodes.INTERNAL_VERIFICATION_FAILED, message)

    def verify_no_captures(self, new_workspace: Workspace, offset: int, kind: str, name: str, plan: _Plan) -> None:
        failed = self._verification_failed
        new_file = new_workspace.file(self.file.path)
        node_type = ast.Lambda if kind == "lambda" else ast.FunctionDef
        generated = None
        for node in ast.walk(new_file.tree):
            if isinstance(node, node_type) and new_file.start_offset(node) == offset:
                generated = node
                break
        if generated is None:
            raise failed("The generated function cannot be found in the edited file.")
        new_bindings = analyze_workspace(new_workspace)
        new_module = new_bindings.modules[new_file.module_key]
        new_scope = new_module.scope_of(generated)
        if new_scope is None:
            raise failed("The generated function has no scope.")
        original_global_names = {
            o.symbol.name
            for o in self.index.within(self.start, self.end)
            if o.symbol.kind in (SymbolKind.BUILTIN, SymbolKind.UNRESOLVED_NAME)
            or (o.symbol.kind is SymbolKind.BINDING and o.symbol.module == self.file.module_key and not o.symbol.scope)
        }
        path = new_scope.path
        new_index = OccurrenceIndex(new_module.occurrences)
        for occurrence in new_index.within(new_file.start_offset(generated), new_file.end_offset(generated)):
            if occurrence.node is generated:
                continue
            for symbol in [occurrence.symbol, *occurrence.alternatives]:
                is_global_lookup = not symbol.scope and (
                    symbol.kind is not SymbolKind.BINDING or symbol.module == new_file.module_key
                )
                if symbol.kind is SymbolKind.BINDING and symbol.module == new_file.module_key and symbol.scope:
                    if symbol.scope[: len(path)] != path:
                        raise failed(f"{occurrence.source_name} is captured by the generated function.")
                elif is_global_lookup and occurrence.role in _READ_ROLES and symbol.name not in original_global_names:
                    raise failed(f"{occurrence.source_name} became a global lookup in the generated function.")
        try:
            table = symtable.symtable(new_file.text, new_file.path, "exec")
        except SyntaxError as error:
            raise failed(f"The symbol table of the edited file cannot be built: {error}") from error
        parameters = tuple(symbol.name for symbol in plan.parameters)
        found = False
        stack = list(table.get_children())
        while stack:
            current = stack.pop()
            stack.extend(current.get_children())
            names = ("lambda", "<lambda>") if kind == "lambda" else (name,)
            if current.get_type() != "function" or current.get_name() not in names:
                continue
            if current.get_lineno() != generated.lineno or tuple(current.get_parameters()) != parameters:
                continue
            found = True
            if current.get_frees():
                raise failed(f"The generated function has free variables: {', '.join(current.get_frees())}.")
            for symbol in current.get_symbols():
                if symbol.is_nonlocal() or symbol.is_declared_global():
                    raise failed(f"The generated function declares {symbol.get_name()} global or nonlocal.")
        if not found:
            raise failed("The generated function is missing from the symbol table of the edited file.")


@returning_refusals
def extract_iife(request: ExtractIifeRequest, workspace: Workspace) -> Result:
    return _Extraction(request, workspace).extract()
