"""Rename: renames a local, parameter, function, class, or module-level name and every reference to it.

See docs/rename.md. The steps follow the specification's algorithm:
  1. Resolve the symbols at the cursor, and close them over imports: `from m import x` (without `as`) makes the
     importing module's name the same name as `m.x`, so they are renamed together.
  2. Refuse what is not a plain name: attributes (anything reached with `obj.name`, which includes everything
     bound in a class body), builtins, names from outside the workspace, names the runtime looks up by
     spelling (dunder names), and names that dynamic code may use by spelling.
  3. Parameters can be passed by keyword: renaming one needs every call that may pass it to be found.
  4. Edit every occurrence (and the matching strings of `__all__`), then run the re-binding check.
"""

import ast
import keyword
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

from riktigrefactor.protocol import (
    Location,
    RefactoringWarning,
    RefusalCodes,
    RefusalError,
    RenameRequest,
    Result,
    Success,
    TextEdit,
    returning_refusals,
)
from riktigrefactor.semantics import (
    DynamicNameUse,
    Occurrence,
    OccurrenceRole,
    ScopeKind,
    Symbol,
    SymbolKind,
    WorkspaceBindings,
    analyze_workspace,
)
from riktigrefactor.verification import verify_edits
from riktigrefactor.workspace import SourceFile, Workspace


class RenameRefusalCodes:
    """The refusal codes of Rename; refusal-codes.md is the source of truth."""

    NOT_RENAMEABLE = "not-renameable"
    ATTRIBUTE_NOT_SUPPORTED = "attribute-not-supported"
    INVALID_IDENTIFIER = "invalid-identifier"
    RUNTIME_PROTOCOL_NAME = "runtime-protocol-name"
    PRIVATE_NAME = "private-name"
    BINDING_WOULD_CHANGE = "binding-would-change"
    DYNAMIC_ACCESS_POSSIBLE = "dynamic-access-possible"
    KEYWORD_CALLEE_UNKNOWN = "keyword-callee-unknown"
    PARAMETER_KEYWORD_USE_POSSIBLE = "parameter-keyword-use-possible"
    DUNDER_ALL_NOT_ANALYZABLE = "dunder-all-not-analyzable"
    STRING_NAMES_SYMBOL = "string-names-symbol"


STRING_MATCHES_NAME_WARNING = "string-matches-name"

_SCOPE_BASED_DYNAMIC_BUILTINS = {"eval", "exec", "compile"}
_LOCALS_BUILTINS = {"locals", "vars", "dir"}
_DYNAMIC_BUILTIN_NAMES = _SCOPE_BASED_DYNAMIC_BUILTINS | _LOCALS_BUILTINS | {"globals"}
_FRAME_ATTRIBUTES_REACHING_ANY_LOCALS = {"_getframe", "currentframe", "_current_frames", "f_locals", "f_back"}
_FRAME_ATTRIBUTES_REACHING_GLOBALS = {"f_globals", "__globals__"}
_GETATTR_FAMILY = {"getattr", "setattr", "delattr", "hasattr"}
_BINDING_CHANGED_MARKERS = (" binds to ", "would be the same symbol", "do not bind to the same symbols")


def _refuse(code: str, message: str, location: Location | None = None) -> RefusalError:
    return RefusalError(code, message, location)


def _location_of(bindings: WorkspaceBindings, occurrence: Occurrence) -> Location:
    return bindings.workspace.files[occurrence.file].location_of_offsets(occurrence.start_offset, occurrence.end_offset)


class _Parents:
    """Parent of each ast node, per file."""

    def __init__(self) -> None:
        self._by_file: dict[str, dict[int, ast.AST]] = {}

    def of(self, file: SourceFile, node: ast.AST) -> ast.AST | None:
        parents = self._by_file.get(file.path)
        if parents is None:
            parents = {}
            for parent in ast.walk(file.tree):
                for child in ast.iter_child_nodes(parent):
                    parents[id(child)] = parent
            self._by_file[file.path] = parents
        return parents.get(id(node))


@dataclass
class _Context:
    workspace: Workspace
    bindings: WorkspaceBindings
    parents: _Parents
    cache: dict = field(default_factory=dict)

    def file(self, path: str) -> SourceFile:
        return self.workspace.files[path]


@dataclass(frozen=True)
class RenamePlan:
    """A rename's edits and the symbols it renames, before the re-binding check (see `verify_rename_plan`)."""

    edits: tuple[TextEdit, ...]
    renamed_symbols: dict[Symbol, str]
    warnings: tuple[RefactoringWarning, ...]


@returning_refusals
def rename(request: RenameRequest, workspace: Workspace) -> Result:
    plan = plan_rename(request, workspace)
    verify_rename_plan(workspace, plan)
    return Success(workspace.root_text, plan.edits, plan.warnings)


def plan_rename(request: RenameRequest, workspace: Workspace) -> RenamePlan:
    """Checks every precondition except the re-binding check, and returns the edits; raises `RefusalError` to refuse."""
    file = workspace.file(request.file)
    offset = file.offset_of_position(request.position)
    bindings = analyze_workspace(workspace)
    context = _Context(workspace, bindings, _Parents())

    at_cursor = bindings.occurrences_at_cursor(file.path, offset)
    if not at_cursor:
        raise _refuse(RefusalCodes.NO_SYMBOL, "There is no name at the cursor.")
    for occurrence in at_cursor:
        _refuse_unsupported_kind(context, occurrence, occurrence.symbol)
    symbols = _close_over_imports(context, {occurrence.symbol for occurrence in at_cursor})
    occurrences = _occurrences_to_rename(context, symbols)
    old_spellings = {occurrence.source_name for occurrence in occurrences}

    new_name = request.new_name
    _check_new_name(new_name)
    _check_old_names(context, occurrences)
    if old_spellings == {new_name}:
        return RenamePlan((), {}, ())

    _refuse_ambiguous_class_lookups(context, symbols)
    _refuse_dynamic_access(context, symbols, new_name)
    _refuse_submodule_name_clash(context, symbols, new_name)
    _refuse_main_module_reach(context, symbols)
    _refuse_string_annotations(context, symbols, new_name)
    for symbol in symbols:
        _check_parameter(context, symbol)

    edits = [
        workspace.edit(occurrence.file, occurrence.start_offset, occurrence.end_offset, new_name)
        for occurrence in occurrences
    ]
    edits.extend(_edits_for_observable_source_text(context, occurrences))
    string_edits = _dunder_all_edits(context, symbols, new_name)
    edits.extend(string_edits.edits)
    warnings = _string_warnings(context, symbols, string_edits.updated_spans)
    renamed_symbols = {symbol: new_name for symbol in symbols}
    return RenamePlan(tuple(sorted(edits, key=_edit_order)), renamed_symbols, tuple(warnings))


def _edit_order(edit: TextEdit) -> tuple[str, int, int]:
    return edit.file, edit.start.line, edit.start.column


def verify_rename_plan(workspace: Workspace, plan: RenamePlan) -> None:
    """The re-binding check of a planned rename; raises `RefusalError` to refuse."""
    if not plan.edits:
        return
    new_name = next(iter(plan.renamed_symbols.values()))
    try:
        verify_edits(workspace, plan.edits, renamed_symbols=plan.renamed_symbols)
    except RefusalError as error:
        if error.code != RefusalCodes.INTERNAL_VERIFICATION_FAILED:
            raise
        if any(marker in error.message for marker in _BINDING_CHANGED_MARKERS):
            raise _refuse(
                RenameRefusalCodes.BINDING_WOULD_CHANGE,
                f"After the rename, a name would refer to something else: {error.message}",
            ) from error
        if "does not compile" in error.message and new_name not in keyword.softkwlist:
            raise _refuse(
                RenameRefusalCodes.BINDING_WOULD_CHANGE,
                f"The renamed program would not compile, because the new name collides with another name: {error.message}",
            ) from error
        if new_name in keyword.softkwlist and ("parse" in error.message or "compile" in error.message):
            raise _refuse(
                RenameRefusalCodes.INVALID_IDENTIFIER,
                f"{new_name} is a soft keyword, and using it here changes how the program parses.",
            ) from error
        raise


# ---- symbols at the cursor -------------------------------------------------------------------------------


def _refuse_unsupported_kind(context: _Context, occurrence: Occurrence, symbol: Symbol) -> None:
    location = _location_of(context.bindings, occurrence)
    name = occurrence.source_name
    kind = symbol.kind
    if kind is SymbolKind.ATTRIBUTE or (
        kind is SymbolKind.BINDING and symbol.scope and symbol.scope[-1].kind is ScopeKind.CLASS
    ):
        raise _refuse(
            RenameRefusalCodes.ATTRIBUTE_NOT_SUPPORTED,
            f"{name} is an attribute of a class or an object; Rename supports names only, not attributes.",
            location,
        )
    if kind is SymbolKind.KEYWORD_OF_UNKNOWN_CALLEE:
        raise _refuse(
            RenameRefusalCodes.KEYWORD_CALLEE_UNKNOWN,
            f"The function that is called with the keyword {name}= cannot be determined, so its parameter is unknown.",
            location,
        )
    if kind is SymbolKind.BUILTIN:
        raise _refuse(RenameRefusalCodes.NOT_RENAMEABLE, f"{name} is a builtin name.", location)
    if kind is SymbolKind.KEYWORD_OF_BUILTIN:
        raise _refuse(RenameRefusalCodes.NOT_RENAMEABLE, f"{name} is a parameter of a builtin.", location)
    if kind is SymbolKind.MODULE:
        raise _refuse(RenameRefusalCodes.NOT_RENAMEABLE, f"{name} is a module; renaming modules is not supported.", location)
    if kind is SymbolKind.EXTERNAL:
        raise _refuse(RenameRefusalCodes.NOT_RENAMEABLE, f"{name} comes from outside the workspace.", location)
    if kind is SymbolKind.UNRESOLVED_NAME:
        raise _refuse(RenameRefusalCodes.NOT_RENAMEABLE, f"{name} is not defined in the workspace.", location)


def _same_span_partners(context: _Context, occurrence: Occurrence) -> list[Occurrence]:
    module = context.bindings.module_of_file(occurrence.file)
    return [
        other
        for other in module.occurrences_of_node(occurrence.node)
        if other is not occurrence and other.span == occurrence.span
    ]


def _close_over_imports(context: _Context, start: set[Symbol]) -> set[Symbol]:
    """`from m import x` binds the local name x to m.x under the same spelling, so both are renamed together."""
    included: set[Symbol] = set()
    queue = list(start)
    while queue:
        symbol = queue.pop()
        if symbol in included:
            continue
        included.add(symbol)
        for occurrence in context.bindings.occurrences_of(symbol):
            if occurrence.role not in (OccurrenceRole.IMPORT_BINDING, OccurrenceRole.IMPORT_SOURCE_NAME):
                continue
            partners = _same_span_partners(context, occurrence)
            if (
                occurrence.role is OccurrenceRole.IMPORT_BINDING
                and not partners
                and isinstance(occurrence.node, ast.alias)
                and occurrence.node.asname is None
            ):
                raise _refuse(
                    RenameRefusalCodes.NOT_RENAMEABLE,
                    f"{occurrence.source_name} is bound by `import {occurrence.node.name}`, which names a module; "
                    "write `import ... as` first to rename the local name.",
                    _location_of(context.bindings, occurrence),
                )
            for partner in partners:
                _refuse_unsupported_kind(context, partner, partner.symbol)
                queue.append(partner.symbol)
    return included


def _occurrences_to_rename(context: _Context, symbols: Iterable[Symbol]) -> list[Occurrence]:
    by_span: dict[tuple[str, int, int], Occurrence] = {}
    for symbol in symbols:
        for occurrence in context.bindings.occurrences_of(symbol):
            by_span.setdefault((occurrence.file, *occurrence.span), occurrence)
    return sorted(by_span.values(), key=lambda o: (o.file, o.start_offset))


# ---- names ------------------------------------------------------------------------------------------------


def _check_new_name(new_name: str) -> None:
    if not new_name.isidentifier() or keyword.iskeyword(new_name):
        raise _refuse(RenameRefusalCodes.INVALID_IDENTIFIER, f"{new_name!r} is not a valid identifier.")
    if unicodedata.normalize("NFKC", new_name) != new_name:
        raise _refuse(
            RenameRefusalCodes.INVALID_IDENTIFIER,
            f"{new_name!r} is not NFKC-normalized, so Python would read it as a different name.",
        )
    _check_not_special_spelling(new_name, "The new name")


def _check_not_special_spelling(name: str, description: str) -> None:
    if name.startswith("__") and name.endswith("__") and len(name) > 4:
        raise _refuse(
            RenameRefusalCodes.RUNTIME_PROTOCOL_NAME,
            f"{description} {name} is a dunder name, which Python looks up by spelling.",
        )
    if name.startswith("__"):
        raise _refuse(
            RenameRefusalCodes.PRIVATE_NAME,
            f"{description} {name} starts with two underscores, which makes it a private name that Python mangles; "
            "Rename does not support it.",
        )


def _check_old_names(context: _Context, occurrences: list[Occurrence]) -> None:
    for occurrence in occurrences:
        _check_not_special_spelling(occurrence.source_name, "The name")


# ---- class bodies ------------------------------------------------------------------------------------------


def _refuse_ambiguous_class_lookups(context: _Context, symbols: set[Symbol]) -> None:
    for occurrence in context.bindings.occurrences:
        if occurrence.alternatives and any(alternative in symbols for alternative in occurrence.alternatives):
            raise _refuse(
                RenameRefusalCodes.BINDING_WOULD_CHANGE,
                f"{occurrence.source_name} here is looked up in a class namespace first and falls back to the name "
                "being renamed; which one it reads depends on when it runs.",
                _location_of(context.bindings, occurrence),
            )


# ---- dynamic access ----------------------------------------------------------------------------------------


def _find_dynamic_access(
    context: _Context, symbols: Iterable[Symbol], new_name: str | None = None
) -> tuple[str, Location | None] | None:
    """Returns a description (and where) of code that may use one of the symbols by its spelling, or None.

    `new_name` is also looked for in the strings that are given to the runtime: after the rename, those would
    find something else.
    """
    symbols = list(symbols)
    global_symbols = [symbol for symbol in symbols if symbol.is_module_global]
    global_modules = {symbol.module for symbol in global_symbols}
    for use in context.bindings.dynamic_name_uses():
        file = context.file(use.file)
        if use.kind == "star-import":
            if global_symbols and (use.detail in global_modules or file.module_key in global_modules):
                return f"a `from {use.detail} import *` in {use.file}", file.location_of_offsets(
                    use.start_offset, use.end_offset
                )
    for builtin_name, occurrence in _dynamic_builtin_reads(context):
        if _dynamic_builtin_may_use(context, builtin_name, occurrence, symbols):
            file = context.file(occurrence.file)
            return f"a use of {builtin_name} in {occurrence.file}", file.location_of_offsets(
                occurrence.start_offset, occurrence.end_offset
            )
    found = _find_frame_introspection(context, bool(global_symbols))
    if found is not None:
        return found
    if global_symbols:
        found = _find_name_strings_given_to_the_runtime(context, global_symbols, new_name)
        if found is not None:
            return found
    return None


def _dynamic_builtin_reads(context: _Context) -> list[tuple[str, Occurrence]]:
    """Every read of eval, exec, compile, globals, locals, vars, or dir (`dir()` without arguments only), however spelled.

    That includes `builtins.eval`, `from builtins import eval`, and an alias: `g = globals`.
    """
    cached = context.cache.get("dynamic-builtin-reads")
    if cached is not None:
        return cached
    bindings = context.bindings
    reads: list[tuple[str, Occurrence]] = []
    for occurrence in bindings.occurrences:
        if occurrence.role is OccurrenceRole.READ:
            origin = bindings.origin_of(occurrence.symbol)
            name = origin.name
            is_builtin = origin.kind is SymbolKind.BUILTIN or (
                origin.kind is SymbolKind.EXTERNAL and origin.module == "builtins"
            )
            if is_builtin and name in _DYNAMIC_BUILTIN_NAMES:
                reads.append((name, occurrence))
        elif (
            occurrence.role is OccurrenceRole.ATTRIBUTE_READ
            and occurrence.source_name in _DYNAMIC_BUILTIN_NAMES
            and _is_builtins_namespace(context, occurrence)
        ):
            reads.append((occurrence.source_name, occurrence))
    kept = []
    for name, occurrence in reads:
        if name == "dir":
            file = context.file(occurrence.file)
            node = occurrence.node
            parent = context.parents.of(file, node)
            if isinstance(parent, ast.Call) and parent.func is node and (parent.args or parent.keywords):
                continue
        kept.append((name, occurrence))
    context.cache["dynamic-builtin-reads"] = kept
    return kept


def _is_builtins_namespace(context: _Context, attribute_occurrence: Occurrence) -> bool:
    """True for `builtins.x` (the module, however imported) and for `__builtins__.x`."""
    base = attribute_occurrence.node.value
    if not isinstance(base, ast.Name):
        return False
    if base.id == "__builtins__":
        return True
    module = context.bindings.module_of_file(attribute_occurrence.file)
    for occurrence in module.occurrences_of_node(base):
        origin = context.bindings.origin_of(occurrence.symbol)
        if origin.kind is SymbolKind.EXTERNAL and origin.name == "" and origin.module == "builtins":
            return True
    return False


def _find_frame_introspection(context: _Context, includes_module_globals: bool) -> tuple[str, Location | None] | None:
    """Frames expose locals (of callers too, through `f_back`) and globals by spelling."""
    for file in context.workspace.files.values():
        for node in ast.walk(file.tree):
            if not isinstance(node, ast.Attribute):
                continue
            if node.attr in _FRAME_ATTRIBUTES_REACHING_ANY_LOCALS or (
                includes_module_globals and node.attr in _FRAME_ATTRIBUTES_REACHING_GLOBALS
            ):
                return f"the frame or namespace access .{node.attr} in {file.path}", file.location_of_node(node)
    return None


def _dynamic_builtin_may_use(
    context: _Context, builtin_name: str, call_site: Occurrence, symbols: list[Symbol]
) -> bool:
    call_scope_path = call_site.scope.path
    file = context.file(call_site.file)
    for symbol in symbols:
        if builtin_name in _SCOPE_BASED_DYNAMIC_BUILTINS:
            # Code run by eval or exec can import any module and read or write its globals.
            if symbol.is_module_global:
                return True
            if symbol.module == file.module_key and call_scope_path[: len(symbol.scope)] == symbol.scope:
                return True
        elif symbol.module != file.module_key:
            continue
        elif builtin_name == "globals":
            if symbol.is_module_global:
                return True
        elif builtin_name in _LOCALS_BUILTINS:
            if _locals_of_scope_include(context, call_site, symbol):
                return True
    return False


def _locals_of_scope_include(context: _Context, call_site: Occurrence, symbol: Symbol) -> bool:
    """`locals()` lists the variables of the function that it runs in: its own, those of comprehensions inlined in it,
    and the free variables that it (or a function nested in it) reads from the enclosing function."""
    call_path = call_site.scope.path
    scope = call_site.scope
    while scope.kind is ScopeKind.COMPREHENSION and scope.parent is not None:
        scope = scope.parent
    function_path = scope.path
    if symbol.scope in (call_path, function_path):
        return True
    if function_path[: len(symbol.scope)] == symbol.scope and len(symbol.scope) < len(function_path):
        return any(
            occurrence.scope.path[: len(function_path)] == function_path
            for occurrence in context.bindings.occurrences_of(symbol)
        )
    return False


def _find_name_strings_given_to_the_runtime(
    context: _Context, global_symbols: list[Symbol], new_name: str | None = None
) -> tuple[str, Location | None] | None:
    names = {symbol.name for symbol in global_symbols}
    if new_name is not None:
        names.add(new_name)
    for file in context.workspace.files.values():
        module = context.bindings.module_of_file(file.path)
        for node in ast.walk(file.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _GETATTR_FAMILY:
                for argument in node.args[1:2]:
                    if (
                        isinstance(argument, ast.Constant)
                        and argument.value in names
                        and not _is_workspace_class_name(context, module, node.args[0])
                    ):
                        return f"{node.func.id}(..., {argument.value!r}) in {file.path}", file.location_of_node(node)
            if isinstance(node, ast.Attribute) and node.attr == "__dict__" and _is_module_name(context, module, node.value):
                return f"the __dict__ of a module in {file.path}", file.location_of_node(node)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("vars", "dir")
                and len(node.args) == 1
                and _is_module_name(context, module, node.args[0])
            ):
                return f"vars() of a module in {file.path}", file.location_of_node(node)
    return None


def _is_workspace_class_name(context: _Context, module, node: ast.AST) -> bool:
    """True for a name that is bound only by `class` statements: attributes of a class are not module globals."""
    if not isinstance(node, ast.Name):
        return False
    for occurrence in module.occurrences_of_node(node):
        definitions = context.bindings.binding_occurrences_of(context.bindings.origin_of(occurrence.symbol))
        if definitions and all(
            d.role is OccurrenceRole.DEFINITION and isinstance(d.node, ast.ClassDef) for d in definitions
        ):
            return True
    return False


def _is_module_name(context: _Context, module, node: ast.AST) -> bool:
    if not isinstance(node, ast.Name):
        return False
    for occurrence in module.occurrences_of_node(node):
        origin = context.bindings.origin_of(occurrence.symbol)
        if origin.kind in (SymbolKind.MODULE, SymbolKind.EXTERNAL) and origin.name == "":
            return True
    return False


def _refuse_dynamic_access(context: _Context, symbols: set[Symbol], new_name: str | None = None) -> None:
    found = _find_dynamic_access(context, symbols, new_name)
    if found is not None:
        description, location = found
        raise _refuse(
            RenameRefusalCodes.DYNAMIC_ACCESS_POSSIBLE,
            f"{description} may use the name by its spelling, which Rename cannot follow.",
            location,
        )


# ---- modules and packages -----------------------------------------------------------------------------------


def _known_module_names(context: _Context) -> set[str]:
    names: set[str] = set()
    for module_name in context.workspace.modules:
        parts = module_name.split(".")
        for length in range(1, len(parts) + 1):
            names.add(".".join(parts[:length]))
    return names


def _refuse_submodule_name_clash(context: _Context, symbols: set[Symbol], new_name: str) -> None:
    """A global of a package's `__init__` and a submodule of that package are both attributes of the package.

    Importing the submodule rebinds the attribute, so a global that has the submodule's name (before or after
    the rename) is overwritten or shadowed depending on the order of imports.
    """
    known = _known_module_names(context)
    for symbol in symbols:
        if not symbol.is_module_global:
            continue
        module = context.bindings.modules.get(symbol.module)
        if module is None or not module.file.path.replace("\\", "/").endswith("__init__.py"):
            continue
        for name in (symbol.name, new_name):
            if f"{symbol.module}.{name}" in known:
                raise _refuse(
                    RenameRefusalCodes.BINDING_WOULD_CHANGE,
                    f"{name} is also the name of a submodule of the package {symbol.module}; importing the "
                    "submodule binds the same attribute of the package, so the rename could change which one wins.",
                )


def _is_main_guard(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "__name__"):
        return False
    return any(isinstance(c, ast.Constant) and c.value == "__main__" for c in node.comparators)


def _workspace_imports_dunder_main(context: _Context) -> bool:
    cached = context.cache.get("imports-main")
    if cached is not None:
        return cached
    found = False
    for file in context.workspace.files.values():
        compared = {id(c) for node in ast.walk(file.tree) if isinstance(node, ast.Compare) for c in node.comparators}
        for node in ast.walk(file.tree):
            if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "__main__" for a in node.names):
                found = True
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "__main__":
                found = True
            elif isinstance(node, ast.Constant) and node.value == "__main__" and id(node) not in compared:
                found = True  # sys.modules["__main__"], import_module("__main__"), ...
    context.cache["imports-main"] = found
    return found


def _imported_module_keys(context: _Context) -> set[str]:
    bindings = context.bindings
    keys: set[str] = set()
    for occurrence in bindings.occurrences:
        if occurrence.role is OccurrenceRole.IMPORT_BINDING:
            origin = bindings.origin_of(occurrence.symbol)
            if origin.kind is SymbolKind.MODULE:
                keys.add(origin.module)
        elif occurrence.role is OccurrenceRole.IMPORT_SOURCE_NAME:
            keys.add(occurrence.symbol.module)
    for use in bindings.dynamic_name_uses():
        if use.kind == "star-import":
            keys.add(use.detail)
    return keys


def _module_may_run_as_main(context: _Context, module_key: str) -> bool:
    module = context.bindings.modules[module_key]
    stem = module.file.path.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".py")
    if stem in ("main", "__main__"):
        return True
    if any(_is_main_guard(node) for node in ast.walk(module.file.tree)):
        return True
    return module_key not in _imported_module_keys(context)


def _refuse_main_module_reach(context: _Context, symbols: set[Symbol]) -> None:
    """`import __main__` reaches the globals of the script that runs, by attribute, from any module."""
    global_modules = sorted({symbol.module for symbol in symbols if symbol.is_module_global})
    if not global_modules or not _workspace_imports_dunder_main(context):
        return
    for module_key in global_modules:
        if _module_may_run_as_main(context, module_key):
            raise _refuse(
                RenameRefusalCodes.DYNAMIC_ACCESS_POSSIBLE,
                f"The workspace imports __main__, which can be {module_key}; its globals would then be read by "
                "their spelling as attributes that Rename cannot follow.",
            )


# ---- parameters --------------------------------------------------------------------------------------------


def _check_parameter(context: _Context, symbol: Symbol) -> None:
    """A parameter can be passed by keyword: every call that may do so has to be known, or there must be none."""
    bindings = context.bindings
    parameter_occurrences = [o for o in bindings.binding_occurrences_of(symbol) if o.role is OccurrenceRole.PARAMETER]
    for occurrence in parameter_occurrences:
        owner = occurrence.scope.node
        arguments = owner.args
        parameter = occurrence.node
        is_passed_by_keyword_possible = not (
            any(parameter is other for other in arguments.posonlyargs)
            or parameter is arguments.vararg
            or parameter is arguments.kwarg
        )
        if not is_passed_by_keyword_possible:
            continue
        calls = _all_calls_of_function_if_known(context, owner)
        if calls is not None:
            for call in calls:
                if any(keyword_argument.arg is None for keyword_argument in call.keywords):
                    raise _refuse(
                        RenameRefusalCodes.PARAMETER_KEYWORD_USE_POSSIBLE,
                        f"The function is called with ** unpacking, which may pass {occurrence.source_name} by keyword.",
                        _location_of(bindings, occurrence),
                    )
            continue
        _refuse_if_keyword_use_possible(context, symbol, occurrence)


def _refuse_if_keyword_use_possible(context: _Context, symbol: Symbol, parameter_occurrence: Occurrence) -> None:
    """The function may be called in ways the tool cannot trace: it must then be impossible to pass this name."""
    bindings = context.bindings
    for occurrence in bindings.occurrences:
        if occurrence.symbol.kind is SymbolKind.KEYWORD_OF_UNKNOWN_CALLEE and occurrence.symbol.name == symbol.name:
            raise _refuse(
                RenameRefusalCodes.PARAMETER_KEYWORD_USE_POSSIBLE,
                f"The function may be called in ways that are not traced (it is a method, a lambda, decorated, or "
                f"used as a value), and {occurrence.source_name}= is passed by keyword to some callee.",
                _location_of(bindings, occurrence),
            )
    for use in bindings.dynamic_name_uses():
        if use.kind == "keyword-unpacking-call":
            if _callee_is_builtin_name(context, use):
                continue
            file = context.file(use.file)
            raise _refuse(
                RenameRefusalCodes.PARAMETER_KEYWORD_USE_POSSIBLE,
                f"The function may be called in ways that are not traced (it is a method, a lambda, decorated, or "
                f"used as a value), and a call with ** unpacking may pass {parameter_occurrence.source_name} by keyword.",
                file.location_of_offsets(use.start_offset, use.end_offset),
            )


def _callee_is_builtin_name(context: _Context, use: DynamicNameUse) -> bool:
    """True when a `**` call's callee is a plain name that is a builtin (not shadowed): it cannot call a workspace function."""
    return any(
        occurrence.span == (use.start_offset, use.end_offset)
        and occurrence.role is OccurrenceRole.READ
        and occurrence.symbol.kind is SymbolKind.BUILTIN
        for occurrence in context.bindings.occurrences_in_file(use.file)
    )


def _all_calls_of_function_if_known(context: _Context, owner: ast.AST) -> list[ast.Call] | None:
    """The calls of an undecorated, never-reassigned def that is only ever called by name; None if not provable."""
    if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)) or owner.decorator_list:
        return None
    bindings = context.bindings
    defining = [
        o
        for file in context.workspace.files.values()
        for o in bindings.module_of_file(file.path).occurrences_of_node(owner)
        if o.role is OccurrenceRole.DEFINITION
    ]
    if len(defining) != 1:
        return None
    function_symbol = defining[0].symbol
    if function_symbol.kind is not SymbolKind.BINDING:
        return None
    if function_symbol.scope and function_symbol.scope[-1].kind is ScopeKind.CLASS:
        return None
    if len(bindings.binding_occurrences_of(function_symbol)) != 1:
        return None
    if _find_dynamic_access(context, [function_symbol]) is not None:
        return None
    if bindings.global_may_be_rebound_elsewhere(function_symbol):
        return None
    calls: list[ast.Call] = []
    for occurrence in bindings.occurrences_with_origin(function_symbol):
        if occurrence.alternatives:
            return None
        if occurrence.role is OccurrenceRole.IMPORT_SOURCE_NAME:
            for partner in _same_span_partners_or_alias_binding(context, occurrence):
                if bindings.origin_of(partner.symbol) != function_symbol:
                    return None
        elif occurrence.role in (OccurrenceRole.DEFINITION, OccurrenceRole.IMPORT_BINDING):
            continue
        elif occurrence.role in (OccurrenceRole.READ, OccurrenceRole.ATTRIBUTE_READ):
            file = context.file(occurrence.file)
            parent = context.parents.of(file, occurrence.node)
            if not (isinstance(parent, ast.Call) and parent.func is occurrence.node):
                return None
            calls.append(parent)
        else:
            return None
    return calls


def _same_span_partners_or_alias_binding(context: _Context, source_name: Occurrence) -> list[Occurrence]:
    """The local binding that an import statement creates for an imported name (same alias node)."""
    module = context.bindings.module_of_file(source_name.file)
    return [
        other
        for other in module.occurrences_of_node(source_name.node)
        if other.role is OccurrenceRole.IMPORT_BINDING
    ]


# ---- source text that the program can observe -----------------------------------------------------------------


_CHARACTERS_NOT_SAFE_IN_COPIED_FSTRING_TEXT = "\\'\"\r\n"


def _edits_for_observable_source_text(context: _Context, occurrences: list[Occurrence]) -> list[TextEdit]:
    """f-strings with `=` print the source text of their expression, and template strings keep it.

    `f"{qq=}"` prints `qq=` and then the value; to keep the output when `qq` is renamed, the text moves into
    the literal part: `f"qq={zz!r}"`. (`{qq=}` formats with `repr` when it has neither a conversion nor a format spec;
    with a format spec it uses `format`; `!s` and `!a` are kept.) What cannot be rewritten safely is refused, and
    so is a renamed name in a template string's interpolation, whose `expression` is source text.
    """
    edits: list[TextEdit] = []
    spans_by_file: dict[str, list[tuple[int, int]]] = {}
    for occurrence in occurrences:
        spans_by_file.setdefault(occurrence.file, []).append(occurrence.span)
    interpolation_type = getattr(ast, "Interpolation", None)
    for path, spans in spans_by_file.items():
        file = context.file(path)

        def renamed_inside(start: int, end: int) -> bool:
            return any(start <= span_start and span_end <= end for span_start, span_end in spans)

        nodes = list(ast.walk(file.tree))
        inside_format_spec = {
            id(inner)
            for node in nodes
            if isinstance(node, ast.FormattedValue) and node.format_spec is not None
            for inner in ast.walk(node.format_spec)
        }
        for node in nodes:
            if interpolation_type is not None and isinstance(node, interpolation_type):
                if renamed_inside(file.start_offset(node), file.end_offset(node)):
                    raise _refuse(
                        RenameRefusalCodes.STRING_NAMES_SYMBOL,
                        "A template string keeps the source text of its interpolations (Interpolation.expression), "
                        "which would still name the old spelling.",
                        file.location_of_node(node),
                    )
            if not isinstance(node, ast.JoinedStr):
                continue
            for index, field_node in enumerate(node.values):
                if not isinstance(field_node, ast.FormattedValue):
                    continue
                if not renamed_inside(file.start_offset(field_node), file.end_offset(field_node)):
                    continue
                previous = node.values[index - 1] if index > 0 else None
                edits.extend(
                    _debug_field_edits(context, file, field_node, previous, id(node) in inside_format_spec, renamed_inside)
                )
    return edits


def _debug_field_edits(
    context: _Context, file: SourceFile, field_node: ast.FormattedValue, previous: ast.AST | None, in_spec: bool, renamed_inside
) -> list[TextEdit]:
    text = file.text
    brace = file.start_offset(field_node)
    position = file.end_offset(field_node.value)
    while position < len(text) and (text[position].isspace() or text[position] == ")"):
        position += 1
    if position >= len(text) or text[position] != "=":
        return []  # not a self-documenting field
    equals = position
    after = equals + 1
    while after < len(text) and text[after].isspace():
        after += 1
    if not renamed_inside(brace, equals):
        return []
    debug_text = text[brace + 1 : after]
    where = file.location_of_offsets(brace, after)
    if in_spec or any(c in debug_text for c in _CHARACTERS_NOT_SAFE_IN_COPIED_FSTRING_TEXT):
        raise _refuse(
            RenameRefusalCodes.STRING_NAMES_SYMBOL,
            "An f-string with = prints the source text of its expression, which would name the old spelling, and "
            "the text cannot be copied safely into the literal part of the f-string.",
            where,
        )
    if not (isinstance(previous, ast.Constant) and isinstance(previous.value, str) and previous.value.endswith(debug_text)):
        raise _refuse(
            RenameRefusalCodes.STRING_NAMES_SYMBOL,
            "An f-string with = prints the source text of its expression; the text could not be matched, so it "
            "cannot be kept.",
            where,
        )
    escaped = debug_text.replace("{", "{{").replace("}", "}}")
    conversion = "!r" if after < len(text) and text[after] == "}" else ""
    return [
        context.workspace.edit(file.path, brace, brace, escaped),
        context.workspace.edit(file.path, equals, after, conversion),
    ]


def _refuse_string_annotations(context: _Context, symbols: set[Symbol], new_name: str) -> None:
    """A string annotation is evaluated by name in the module's globals (`typing.get_type_hints`, dataclasses).

    Renaming a global would leave the old spelling in the string (a `NameError` later), or make the string find
    another global that has the new name.
    """
    global_names = {symbol.name for symbol in symbols if symbol.is_module_global}
    if not global_names:
        return
    names = global_names | {new_name}
    for file in context.workspace.files.values():
        for node in ast.walk(file.tree):
            annotations: list[ast.expr | None] = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments = node.args
                every_argument = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
                every_argument += [a for a in (arguments.vararg, arguments.kwarg) if a is not None]
                annotations = [a.annotation for a in every_argument] + [node.returns]
            elif isinstance(node, ast.AnnAssign):
                annotations = [node.annotation]
            for annotation in annotations:
                if annotation is None:
                    continue
                for inner in ast.walk(annotation):
                    if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                        if names & set(re.findall(r"[^\W\d]\w*", inner.value)):
                            raise _refuse(
                                RenameRefusalCodes.STRING_NAMES_SYMBOL,
                                f"The string annotation {inner.value!r} names {sorted(names & set(re.findall(r'[^\W\d]\w*', inner.value)))[0]}; "
                                "string annotations are evaluated by name later and are not rewritten.",
                                file.location_of_node(inner),
                            )


# ---- __all__ and strings -----------------------------------------------------------------------------------


@dataclass
class _StringEdits:
    edits: list[TextEdit]
    updated_spans: set[tuple[str, int]]


def _literal_strings(node: ast.AST | None) -> list[ast.Constant] | None:
    if isinstance(node, (ast.List, ast.Tuple)):
        if all(isinstance(element, ast.Constant) and isinstance(element.value, str) for element in node.elts):
            return list(node.elts)  # type: ignore[arg-type]
    return None


def _dunder_all_strings(context: _Context, module_key: str) -> list[ast.Constant]:
    """Every string that the module's `__all__` is made of; refuses when it is built in a way we cannot read."""
    bindings = context.bindings
    all_symbol = Symbol(SymbolKind.BINDING, module_key, (), "__all__")
    constants: list[ast.Constant] = []
    module_path = bindings.modules[module_key].file.path
    for occurrence in bindings.occurrences_of(all_symbol):
        file = context.file(occurrence.file)
        node = occurrence.node
        parent = context.parents.of(file, node)
        found: list[ast.Constant] | None = None
        if occurrence.file != module_path:
            if occurrence.role in (OccurrenceRole.IMPORT_SOURCE_NAME, OccurrenceRole.IMPORT_BINDING):
                continue
            if occurrence.role is OccurrenceRole.ATTRIBUTE_READ and not isinstance(parent, ast.Attribute):
                continue
        elif isinstance(parent, ast.Assign) and len(parent.targets) == 1 and parent.targets[0] is node:
            found = _literal_strings(parent.value)
        elif isinstance(parent, ast.AnnAssign) and parent.target is node:
            found = _literal_strings(parent.value)
        elif isinstance(parent, ast.AugAssign) and parent.target is node and isinstance(parent.op, ast.Add):
            found = _literal_strings(parent.value)
        elif isinstance(parent, ast.Attribute) and parent.value is node and parent.attr in ("append", "extend"):
            call = context.parents.of(file, parent)
            if isinstance(call, ast.Call) and call.func is parent and len(call.args) == 1 and not call.keywords:
                argument = call.args[0]
                if parent.attr == "append" and isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    found = [argument]
                elif parent.attr == "extend":
                    found = _literal_strings(argument)
        if found is None:
            raise _refuse(
                RenameRefusalCodes.DUNDER_ALL_NOT_ANALYZABLE,
                f"__all__ in {module_key} is not a list or tuple of string literals (or changed only with append, "
                "extend and +=), so the strings that name the renamed name cannot be found.",
                _location_of(bindings, occurrence),
            )
        constants.extend(found)
    return constants


def _dunder_all_edits(context: _Context, symbols: set[Symbol], new_name: str) -> _StringEdits:
    result = _StringEdits([], set())
    for module_key in sorted({symbol.module for symbol in symbols if symbol.is_module_global}):
        module = context.bindings.modules.get(module_key)
        if module is None:
            continue
        names = {symbol.name for symbol in symbols if symbol.is_module_global and symbol.module == module_key}
        file = module.file
        for constant in _dunder_all_strings(context, module_key):
            if constant.value not in names:
                continue
            start, end = file.start_offset(constant), file.end_offset(constant)
            source = file.text[start:end]
            if len(source) != len(constant.value) + 2 or source[0] not in "'\"" or source[1:-1] != constant.value:
                raise _refuse(
                    RenameRefusalCodes.DUNDER_ALL_NOT_ANALYZABLE,
                    f"The string {source} in __all__ is not a plain quoted name.",
                    file.location_of_offsets(start, end),
                )
            result.edits.append(context.workspace.edit(file.path, start + 1, end - 1, new_name))
            result.updated_spans.add((file.path, start))
    return result


def _string_warnings(
    context: _Context, symbols: set[Symbol], updated_spans: set[tuple[str, int]]
) -> list[RefactoringWarning]:
    names = {symbol.name for symbol in symbols}
    if any(symbol.is_module_global for symbol in symbols):
        files = list(context.workspace.files.values())
    else:
        files = [context.file(path) for path in sorted({symbol_file(context, s) for s in symbols})]
    warnings = []
    for file in files:
        for node in ast.walk(file.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in names:
                if (file.path, file.start_offset(node)) in updated_spans:
                    continue
                warnings.append(
                    RefactoringWarning(
                        STRING_MATCHES_NAME_WARNING,
                        f"The string {node.value!r} equals the name that was renamed; strings are not changed.",
                        file.location_of_node(node),
                    )
                )
    return warnings


def symbol_file(context: _Context, symbol: Symbol) -> str:
    return context.bindings.modules[symbol.module].file.path
