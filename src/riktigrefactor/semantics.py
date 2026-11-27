"""The binding model: which symbol every name occurrence in a workspace refers to.

Scopes follow the Language Reference, "Naming and binding" (execution model): module, function, lambda, class,
comprehension, and (Python 3.12+) type-parameter and type-alias-value scopes, plus (3.14+) annotation scopes.
The result is cross-checked against CPython's `symtable` (see symtable_check.py).

Public entry point: `analyze_workspace(workspace)` returns a `WorkspaceBindings` (cached on the workspace).

Vocabulary
  Symbol      A scope-qualified identity: (kind, module, scope path, name).
              A scope is identified by its kind and the offset of the node that creates it, so identities
              stay comparable between the text before and after edits (see verification.py).
  Occurrence  One identifier in the source with its role (read, write, parameter, ...), its exact source span,
              and the Symbol it binds to.
  Alias       A name bound only by an import (`from m import x`, `import m as k`) is an alias of the imported
              Symbol; `WorkspaceBindings.origin_of` follows aliases.

Names are NFKC-normalized and private names are mangled (`__x` in class `C` is `_C__x`) in `Symbol.name`;
`Occurrence.source_name` is the spelling in the source and the span covers exactly that spelling.

Known limits (also in docs/limitations.md)
  - Names that are looked up dynamically (`globals()`, `getattr`, `eval`, `__all__`, star imports) are reported
    in `ModuleBindings.dynamic_name_uses` and are not resolved.
  - Attribute access on anything other than a workspace module is an ATTRIBUTE symbol, shared by spelling.
  - Names in string annotations and string forward references are not looked up.
  - Where a name is looked up in a class namespace first and falls back to an outer scope at run time
    (class bodies, and annotation-like scopes inside classes), the occurrence lists the fallback in
    `Occurrence.alternatives`; it may bind to the symbol or to any alternative.
  - Whether Python 3.14+ annotation scopes apply is decided from the running interpreter's version and
    `from __future__ import annotations`.
"""

import ast
import builtins
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from riktigrefactor import name_locations
from riktigrefactor.protocol import SemanticModelError
from riktigrefactor.symtable_check import ScopeSummary, check_against_symtable
from riktigrefactor.workspace import SourceFile, Workspace

LAZY_ANNOTATIONS_AVAILABLE = sys.version_info >= (3, 14)


class ScopeKind(StrEnum):
    MODULE = "module"
    FUNCTION = "function"
    LAMBDA = "lambda"
    CLASS = "class"
    COMPREHENSION = "comprehension"
    TYPE_PARAMETERS = "type-parameters"
    TYPE_ALIAS_VALUE = "type-alias-value"
    ANNOTATION = "annotation"


_ANNOTATION_LIKE_KINDS = {ScopeKind.TYPE_PARAMETERS, ScopeKind.TYPE_ALIAS_VALUE, ScopeKind.ANNOTATION}
_SCOPES_FOUND_BY_NODE = {
    ScopeKind.MODULE,
    ScopeKind.FUNCTION,
    ScopeKind.LAMBDA,
    ScopeKind.CLASS,
    ScopeKind.COMPREHENSION,
    ScopeKind.TYPE_ALIAS_VALUE,
}


class SymbolKind(StrEnum):
    BINDING = "binding"
    """A variable, parameter, function, class, or import alias bound in some scope (module = the module's key)."""
    BUILTIN = "builtin"
    MODULE = "module"
    """A module of the workspace (or a package directory of it); `module` is its dotted name."""
    EXTERNAL = "external"
    """A module outside the workspace (name == "") or a name imported from one (`module` = the module)."""
    UNRESOLVED_NAME = "unresolved-name"
    """A global name that no module binding or builtin provides, or a member a workspace module does not define."""
    ATTRIBUTE = "attribute"
    """An attribute of an object that is not a workspace module; every attribute with the same spelling is one symbol."""
    KEYWORD_OF_BUILTIN = "keyword-of-builtin"
    KEYWORD_OF_UNKNOWN_CALLEE = "keyword-of-unknown-callee"
    """A keyword argument whose callee is not a plain workspace function, so the parameter it names is unknown."""


@dataclass(frozen=True)
class ScopeKey:
    kind: ScopeKind
    start_offset: int


@dataclass(frozen=True)
class Symbol:
    kind: SymbolKind
    module: str
    scope: tuple[ScopeKey, ...]
    name: str

    @property
    def is_module_global(self) -> bool:
        return self.kind is SymbolKind.BINDING and not self.scope

    def with_name(self, name: str) -> "Symbol":
        return Symbol(self.kind, self.module, self.scope, name)


class OccurrenceRole(StrEnum):
    READ = "read"
    WRITE = "write"
    AUGMENTED_WRITE = "augmented-write"
    """The target of an augmented assignment: it reads and writes."""
    ANNOTATION_ONLY = "annotation-only"
    """`x: int` without a value: makes `x` local to the scope but does not assign it."""
    DELETE = "delete"
    DEFINITION = "definition"
    """The name of a `def`, `class`, or `type` statement."""
    PARAMETER = "parameter"
    IMPORT_BINDING = "import-binding"
    """The name an import statement binds locally."""
    IMPORT_SOURCE_NAME = "import-source-name"
    """The `x` of `from m import x`: a reference to member `x` of module `m` (same span as the binding if no `as`)."""
    EXCEPT_NAME = "except-name"
    MATCH_CAPTURE = "match-capture"
    TYPE_PARAMETER = "type-parameter"
    GLOBAL_DECLARATION = "global-declaration"
    NONLOCAL_DECLARATION = "nonlocal-declaration"
    ATTRIBUTE_READ = "attribute-read"
    ATTRIBUTE_WRITE = "attribute-write"
    ATTRIBUTE_DELETE = "attribute-delete"
    KEYWORD_ARGUMENT = "keyword-argument"
    """The name in `f(name=value)` or in a class statement's keywords."""


BINDING_ROLES = frozenset(
    {
        OccurrenceRole.WRITE,
        OccurrenceRole.AUGMENTED_WRITE,
        OccurrenceRole.ANNOTATION_ONLY,
        OccurrenceRole.DEFINITION,
        OccurrenceRole.PARAMETER,
        OccurrenceRole.IMPORT_BINDING,
        OccurrenceRole.EXCEPT_NAME,
        OccurrenceRole.MATCH_CAPTURE,
        OccurrenceRole.TYPE_PARAMETER,
    }
)


@dataclass(eq=False)
class Scope:
    kind: ScopeKind
    node: ast.AST
    parent: "Scope | None"
    key: ScopeKey | None
    display_name: str
    mangling_class: str | None
    children: list["Scope"] = field(default_factory=list)
    bound_names: set[str] = field(default_factory=set)
    explicitly_global: set[str] = field(default_factory=set)
    explicitly_nonlocal: set[str] = field(default_factory=set)
    classifications: dict[str, str] = field(default_factory=dict)

    @property
    def path(self) -> tuple[ScopeKey, ...]:
        """Keys of this scope and its enclosing scopes, outermost first, excluding the module scope."""
        if self.parent is None:
            return ()
        assert self.key is not None
        return self.parent.path + (self.key,)

    def enclosing_scopes(self) -> Iterator["Scope"]:
        scope = self.parent
        while scope is not None:
            yield scope
            scope = scope.parent


@dataclass(frozen=True, eq=False)
class Occurrence:
    file: str
    start_offset: int
    end_offset: int
    source_name: str
    role: OccurrenceRole
    scope: Scope
    symbol: Symbol
    alternatives: tuple[Symbol, ...]
    node: Any
    """The ast node: `Name`, `arg`, `alias`, `Attribute`, `keyword`, `FunctionDef`/`ClassDef` for definitions, ..."""

    @property
    def span(self) -> tuple[int, int]:
        return self.start_offset, self.end_offset


@dataclass(frozen=True)
class DynamicNameUse:
    """A construct that can refer to names by their spelling, which the binding model cannot follow."""

    file: str
    start_offset: int
    end_offset: int
    kind: str
    """One of: `star-import`, `dunder-all`, `dynamic-builtin` (detail = the builtin's name), `dunder-dict`,
    `keyword-unpacking-call` (detail = the callee's source text)."""
    detail: str = ""


@dataclass
class ModuleBindings:
    file: SourceFile
    root_scope: Scope
    scopes: list[Scope]
    occurrences: list[Occurrence]
    module_level_names: set[str]
    dynamic_name_uses: list[DynamicNameUse]
    has_module_getattr: bool
    scope_by_node_id: dict[int, Scope]
    occurrences_by_node_id: dict[int, list[Occurrence]]

    def scope_of(self, scope_creating_node: ast.AST) -> Scope | None:
        return self.scope_by_node_id.get(id(scope_creating_node))

    def occurrences_of_node(self, node: ast.AST) -> list[Occurrence]:
        return self.occurrences_by_node_id.get(id(node), [])


class WorkspaceBindings:
    def __init__(
        self,
        workspace: Workspace,
        modules: dict[str, ModuleBindings],
        alias_of: dict[Symbol, Symbol],
        rebound_globals: frozenset[Symbol] = frozenset(),
        modules_with_unknown_rebinding: frozenset[str] = frozenset(),
    ) -> None:
        self.workspace = workspace
        self.modules = modules
        self._alias_of = alias_of
        self._rebound_globals = rebound_globals
        self._modules_with_unknown_rebinding = modules_with_unknown_rebinding
        self.occurrences: list[Occurrence] = sorted(
            (occurrence for module in modules.values() for occurrence in module.occurrences),
            key=lambda o: (o.file, o.start_offset, o.end_offset, o.role.value),
        )
        self._by_symbol: dict[Symbol, list[Occurrence]] = {}
        for occurrence in self.occurrences:
            self._by_symbol.setdefault(occurrence.symbol, []).append(occurrence)
        self._by_file: dict[str, list[Occurrence]] = {}
        for occurrence in self.occurrences:
            self._by_file.setdefault(occurrence.file, []).append(occurrence)

    def module_of_file(self, path: str) -> ModuleBindings:
        return self.modules[self.workspace.file(path).module_key]

    def occurrences_in_file(self, path: str) -> list[Occurrence]:
        return self._by_file.get(path, [])

    def occurrences_at_cursor(self, path: str, offset: int) -> list[Occurrence]:
        """Occurrences whose span contains the offset; if none, those whose span ends exactly at it."""
        inside = [o for o in self.occurrences_in_file(path) if o.start_offset <= offset < o.end_offset]
        if inside:
            return inside
        return [o for o in self.occurrences_in_file(path) if o.end_offset == offset]

    def occurrences_of(self, symbol: Symbol) -> list[Occurrence]:
        return self._by_symbol.get(symbol, [])

    def binding_occurrences_of(self, symbol: Symbol) -> list[Occurrence]:
        return [o for o in self.occurrences_of(symbol) if o.role in BINDING_ROLES]

    def origin_of(self, symbol: Symbol) -> Symbol:
        """Follows import aliases to the symbol they import (a symbol that is not an alias is its own origin)."""
        return _follow_aliases(self._alias_of, symbol)

    def alias_chain(self, symbol: Symbol) -> list[Symbol]:
        """The symbol, then each symbol that its import aliases lead through, ending at its origin."""
        chain = [symbol]
        while chain[-1] in self._alias_of and self._alias_of[chain[-1]] not in chain:
            chain.append(self._alias_of[chain[-1]])
        return chain

    def occurrences_with_origin(self, origin: Symbol) -> list[Occurrence]:
        """Occurrences whose symbol, or any alternative, is `origin` or an alias that leads to it."""
        return [
            o
            for o in self.occurrences
            if self.origin_of(o.symbol) == origin or any(self.origin_of(a) == origin for a in o.alternatives)
        ]

    def global_may_be_rebound_elsewhere(self, symbol: Symbol) -> bool:
        """True when code outside the module's own statements may rebind this module global at run time.

        That is an attribute write, `setattr`, or `delattr` on the module object, or reflection that can reach
        the module's namespace (`globals()`, `__dict__`, `sys.modules`, `eval`, `exec`, frames, ...).
        A function with such a global is not "singly defined": its calls may reach another callee.
        """
        if not symbol.is_module_global:
            return False
        if symbol in self._rebound_globals:
            return True
        return "*" in self._modules_with_unknown_rebinding or symbol.module in self._modules_with_unknown_rebinding

    def is_alias(self, symbol: Symbol) -> bool:
        return symbol in self._alias_of

    def dynamic_name_uses(self) -> list[DynamicNameUse]:
        return [use for module in self.modules.values() for use in module.dynamic_name_uses]


def _follow_aliases(alias_of: dict[Symbol, Symbol], symbol: Symbol) -> Symbol:
    seen = {symbol}
    while symbol in alias_of:
        symbol = alias_of[symbol]
        if symbol in seen:
            break
        seen.add(symbol)
    return symbol


def analyze_workspace(workspace: Workspace) -> WorkspaceBindings:
    cached = workspace.analysis_cache.get("bindings")
    if cached is None:
        cached = _WorkspaceAnalyzer(workspace).analyze()
        workspace.analysis_cache["bindings"] = cached
    return cached


def mangled_name(name: str, enclosing_class_name: str | None) -> str:
    if enclosing_class_name is None or not name.startswith("__") or name.endswith("__"):
        return name
    stripped_class_name = enclosing_class_name.lstrip("_")
    if not stripped_class_name:
        return name
    return f"_{stripped_class_name}{name}"


_MODULE_IMPLICIT_NAMES = frozenset(
    {
        "__name__",
        "__file__",
        "__doc__",
        "__package__",
        "__spec__",
        "__loader__",
        "__builtins__",
        "__cached__",
        "__annotations__",
        "__path__",
    }
)
_CLASS_IMPLICIT_NAMES = frozenset({"__module__", "__qualname__", "__firstlineno__", "__static_attributes__"})
_DYNAMIC_BUILTINS = frozenset(
    {"eval", "exec", "compile", "globals", "locals", "vars", "getattr", "setattr", "delattr", "hasattr", "__import__"}
)


# Reflection that can rebind module globals from anywhere: `eval`, `exec`, `compile`, `__import__`, frames, and
# `importlib`; `globals()`, `vars()`, and `locals()` reach the namespace of the module they are in.
_EVERYWHERE_NAMESPACE_BUILTINS = frozenset({"eval", "exec", "compile", "__import__", "import_module"})
_NAMESPACE_BUILTINS = _EVERYWHERE_NAMESPACE_BUILTINS | {"globals", "vars", "locals"}
_NAMESPACE_REACHING_ATTRIBUTES = frozenset(
    {"__dict__", "__globals__", "f_globals", "f_locals", "f_back", "_getframe", "currentframe", "import_module"}
)


@dataclass
class _Pending:
    role: OccurrenceRole
    start_offset: int
    end_offset: int
    spelling: str
    name: str
    scope: Scope
    node: Any
    resolution: str
    """"load", "bind", "attribute", "keyword", or "import-source"."""
    detail: Any = None


@dataclass
class _ImportAliasSpec:
    pending: _Pending
    module: str
    member: str | None
    """None when the alias binds a module."""


class _FileScopeWalker(ast.NodeVisitor):
    """Builds the scope tree and collects every identifier occurrence, without resolving anything yet."""

    def __init__(self, file: SourceFile) -> None:
        self.file = file
        self.scopes: list[Scope] = []
        self.pending: list[_Pending] = []
        self.import_aliases: list[_ImportAliasSpec] = []
        self.scope_by_node_id: dict[int, Scope] = {}
        self.dynamic_name_uses: list[DynamicNameUse] = []
        self.lazy_annotations = LAZY_ANNOTATIONS_AVAILABLE and not self._imports_future_annotations()
        self.root = self._new_scope(ScopeKind.MODULE, file.tree, None, "<module>", None)
        self.scope = self.root

    def _imports_future_annotations(self) -> bool:
        for statement in self.file.tree.body:
            if isinstance(statement, ast.ImportFrom) and statement.module == "__future__":
                if any(alias.name == "annotations" for alias in statement.names):
                    return True
        return False

    def walk(self) -> None:
        for statement in self.file.tree.body:
            self.visit(statement)

    def _new_scope(
        self,
        kind: ScopeKind,
        node: ast.AST,
        parent: Scope | None,
        display_name: str,
        mangling_class: str | None,
    ) -> Scope:
        key = None
        if parent is not None:
            key = ScopeKey(kind, self.file.start_offset(node))
        scope = Scope(kind, node, parent, key, display_name, mangling_class)
        if parent is not None:
            parent.children.append(scope)
        self.scopes.append(scope)
        if kind in _SCOPES_FOUND_BY_NODE:
            self.scope_by_node_id[id(node)] = scope
        return scope

    def _child_scope(self, kind: ScopeKind, node: ast.AST, parent: Scope, display_name: str) -> Scope:
        mangling_class = parent.mangling_class
        if kind is ScopeKind.CLASS:
            mangling_class = node.name  # type: ignore[attr-defined]
        return self._new_scope(kind, node, parent, display_name, mangling_class)

    def _locate(self, locate, *arguments) -> name_locations.Span:
        try:
            return locate(self.file, *arguments)
        except name_locations.NameNotFoundInSource as error:
            raise SemanticModelError(str(error)) from error

    def _add(
        self,
        role: OccurrenceRole,
        span: name_locations.Span,
        node: Any,
        resolution: str,
        lookup_scope: Scope | None = None,
        detail: Any = None,
        name: str | None = None,
    ) -> _Pending:
        start, end, spelling = span
        normalized_name = name if name is not None else name_locations.normalized(spelling)
        mangled = mangled_name(normalized_name, self.scope.mangling_class)
        scope = lookup_scope if lookup_scope is not None else self.scope
        pending = _Pending(role, start, end, spelling, mangled, scope, node, resolution, detail)
        self.pending.append(pending)
        if resolution == "bind" and role in BINDING_ROLES | {OccurrenceRole.DELETE}:
            scope.bound_names.add(mangled)
        return pending

    def _node_span(self, node: ast.AST) -> name_locations.Span:
        start = self.file.start_offset(node)
        end = self.file.end_offset(node)
        return start, end, self.file.text[start:end]

    @contextmanager
    def _within(self, scope: Scope) -> Iterator[Scope]:
        previous = self.scope
        self.scope = scope
        try:
            yield scope
        finally:
            self.scope = previous

    def _visit_all(self, nodes) -> None:
        for node in nodes:
            if node is not None:
                self.visit(node)

    def _nearest_non_comprehension_scope(self) -> Scope:
        scope = self.scope
        while scope.kind is ScopeKind.COMPREHENSION:
            assert scope.parent is not None
            scope = scope.parent
        return scope

    def visit_Name(self, node: ast.Name) -> None:
        span = self._node_span(node)
        if isinstance(node.ctx, ast.Load):
            self._add(OccurrenceRole.READ, span, node, "load")
        elif isinstance(node.ctx, ast.Store):
            self._add(OccurrenceRole.WRITE, span, node, "bind")
        else:
            self._add(OccurrenceRole.DELETE, span, node, "bind")

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._add(
            OccurrenceRole.WRITE,
            self._node_span(node.target),
            node.target,
            "bind",
            lookup_scope=self._nearest_non_comprehension_scope(),
        )

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name):
            self._add(OccurrenceRole.AUGMENTED_WRITE, self._node_span(node.target), node.target, "bind")
        else:
            self.visit(node.target)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        is_simple_name = isinstance(node.target, ast.Name)
        in_function = self.scope.kind in (ScopeKind.FUNCTION, ScopeKind.LAMBDA, ScopeKind.COMPREHENSION)
        if self.lazy_annotations and is_simple_name and not in_function:
            annotation_scope = self._child_scope(ScopeKind.ANNOTATION, node, self.scope, "<annotation>")
            with self._within(annotation_scope):
                self.visit(node.annotation)
        else:
            self.visit(node.annotation)
        if isinstance(node.target, ast.Name):
            role = OccurrenceRole.WRITE if node.value is not None else OccurrenceRole.ANNOTATION_ONLY
            self._add(role, self._node_span(node.target), node.target, "bind")
        else:
            self.visit(node.target)
        if node.value is not None:
            self.visit(node.value)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.visit(node.value)
        end = self.file.end_offset(node)
        span = self._locate(name_locations.identifier_before, end, node.attr)
        roles = {
            ast.Load: OccurrenceRole.ATTRIBUTE_READ,
            ast.Store: OccurrenceRole.ATTRIBUTE_WRITE,
            ast.Del: OccurrenceRole.ATTRIBUTE_DELETE,
        }
        self._add(roles[type(node.ctx)], span, node, "attribute", detail=node.value)
        if node.attr == "__dict__":
            self.dynamic_name_uses.append(DynamicNameUse(self.file.path, span[0], span[1], "dunder-dict"))

    def visit_Call(self, node: ast.Call) -> None:
        self.visit(node.func)
        self._visit_all(node.args)
        for keyword in node.keywords:
            if keyword.arg is None:
                start, end = self.file.start_offset(node.func), self.file.end_offset(node.func)
                self.dynamic_name_uses.append(
                    DynamicNameUse(
                        self.file.path, start, end, "keyword-unpacking-call", self.file.text[start:end]
                    )
                )
            else:
                span = self._locate(name_locations.identifier_at_start, self.file.start_offset(keyword), keyword.arg)
                self._add(OccurrenceRole.KEYWORD_ARGUMENT, span, keyword, "keyword", detail=node.func)
            self.visit(keyword.value)

    def visit_Global(self, node: ast.Global) -> None:
        self._declare(node, OccurrenceRole.GLOBAL_DECLARATION)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self._declare(node, OccurrenceRole.NONLOCAL_DECLARATION)

    def _declare(self, node: ast.Global | ast.Nonlocal, role: OccurrenceRole) -> None:
        spans = self._locate(
            name_locations.declared_names, self.file.start_offset(node), self.file.end_offset(node), list(node.names)
        )
        for span in spans:
            pending = self._add(role, span, node, "bind")
            if role is OccurrenceRole.GLOBAL_DECLARATION:
                self.scope.explicitly_global.add(pending.name)
            else:
                self.scope.explicitly_nonlocal.add(pending.name)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            first, as_span = name_locations.import_alias_names(
                self.file, self.file.start_offset(alias), self.file.end_offset(alias), alias.name, alias.asname
            )
            if alias.asname is not None:
                assert as_span is not None
                pending = self._add(OccurrenceRole.IMPORT_BINDING, as_span, alias, "bind", name=alias.asname)
                self.import_aliases.append(_ImportAliasSpec(pending, alias.name, None))
            else:
                top_package = alias.name.partition(".")[0]
                pending = self._add(OccurrenceRole.IMPORT_BINDING, first, alias, "bind", name=top_package)
                self.import_aliases.append(_ImportAliasSpec(pending, top_package, None))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = self._imported_module_name(node)
        for alias in node.names:
            span_start = self.file.start_offset(alias)
            span_end = self.file.end_offset(alias)
            if alias.name == "*":
                self.dynamic_name_uses.append(DynamicNameUse(self.file.path, span_start, span_end, "star-import", module))
                continue
            first, as_span = name_locations.import_alias_names(self.file, span_start, span_end, alias.name, alias.asname)
            self._add(
                OccurrenceRole.IMPORT_SOURCE_NAME,
                first,
                alias,
                "import-source",
                detail=(module, alias.name),
                name=alias.name,
            )
            if as_span is not None:
                pending = self._add(OccurrenceRole.IMPORT_BINDING, as_span, alias, "bind", name=alias.asname)
            else:
                pending = self._add(OccurrenceRole.IMPORT_BINDING, first, alias, "bind", name=alias.name)
            self.import_aliases.append(_ImportAliasSpec(pending, module, alias.name))

    def _imported_module_name(self, node: ast.ImportFrom) -> str:
        if node.level == 0:
            return node.module or ""
        if self.file.module_name is None:
            return "." * node.level + (node.module or "")
        base = self.file.containing_package_name
        for _ in range(node.level - 1):
            if not base:
                return "." * node.level + (node.module or "")
            base = base.rpartition(".")[0]
        if node.module:
            return f"{base}.{node.module}" if base else node.module
        return base

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:
            self.visit(node.type)
        if node.name is not None:
            assert node.type is not None
            span = self._locate(name_locations.except_handler_name, self.file.end_offset(node.type), node.name)
            self._add(OccurrenceRole.EXCEPT_NAME, span, node, "bind", name=node.name)
        self._visit_all(node.body)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.pattern is not None:
            self.visit(node.pattern)
        if node.name is not None:
            span = self._locate(name_locations.identifier_before, self.file.end_offset(node), node.name)
            self._add(OccurrenceRole.MATCH_CAPTURE, span, node, "bind", name=node.name)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            span = self._locate(name_locations.identifier_before, self.file.end_offset(node), node.name)
            self._add(OccurrenceRole.MATCH_CAPTURE, span, node, "bind", name=node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        self._visit_all(node.keys)
        self._visit_all(node.patterns)
        if node.rest is not None:
            span = self._locate(
                name_locations.mapping_pattern_rest,
                self.file.start_offset(node),
                self.file.end_offset(node),
                node.rest,
            )
            self._add(OccurrenceRole.MATCH_CAPTURE, span, node, "bind", name=node.rest)

    def _visit_type_parameters(self, type_parameters: list[ast.AST], scope: Scope) -> None:
        with self._within(scope):
            for parameter in type_parameters:
                span = self._locate(
                    name_locations.type_parameter_name,
                    self.file.start_offset(parameter),
                    parameter.name,  # type: ignore[attr-defined]
                )
                self._add(OccurrenceRole.TYPE_PARAMETER, span, parameter, "bind", name=parameter.name)  # type: ignore[attr-defined]
                self._visit_all(
                    [
                        getattr(parameter, "bound", None),
                        getattr(parameter, "default_value", None),
                    ]
                )

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        enclosing = self.scope
        self._visit_all(node.decorator_list)
        self._visit_all(node.args.defaults)
        self._visit_all(node.args.kw_defaults)
        header_scope = enclosing
        type_parameters = getattr(node, "type_params", [])
        if type_parameters:
            header_scope = self._child_scope(ScopeKind.TYPE_PARAMETERS, node, enclosing, node.name)
            self._visit_type_parameters(type_parameters, header_scope)
        parameters = self._parameters(node.args)
        annotations = [p.annotation for p in parameters if p.annotation is not None]
        if node.returns is not None:
            annotations.append(node.returns)
        annotation_scope = header_scope
        if self.lazy_annotations and annotations:
            annotation_scope = self._child_scope(ScopeKind.ANNOTATION, node, header_scope, node.name)
        with self._within(annotation_scope):
            self._visit_all(annotations)
        definition_span = self._locate(name_locations.definition_name, self.file.start_offset(node), "def", node.name)
        self._add(OccurrenceRole.DEFINITION, definition_span, node, "bind", lookup_scope=enclosing, name=node.name)
        function_scope = self._child_scope(ScopeKind.FUNCTION, node, header_scope, node.name)
        with self._within(function_scope):
            self._bind_parameters(parameters)
            self._visit_all(node.body)

    visit_AsyncFunctionDef = visit_FunctionDef

    @staticmethod
    def _parameters(arguments: ast.arguments) -> list[ast.arg]:
        parameters = [*arguments.posonlyargs, *arguments.args]
        if arguments.vararg is not None:
            parameters.append(arguments.vararg)
        parameters.extend(arguments.kwonlyargs)
        if arguments.kwarg is not None:
            parameters.append(arguments.kwarg)
        return parameters

    def _bind_parameters(self, parameters: list[ast.arg]) -> None:
        for parameter in parameters:
            span = self._locate(name_locations.identifier_at_start, self.file.start_offset(parameter), parameter.arg)
            self._add(OccurrenceRole.PARAMETER, span, parameter, "bind", name=parameter.arg)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_all(node.args.defaults)
        self._visit_all(node.args.kw_defaults)
        scope = self._child_scope(ScopeKind.LAMBDA, node, self.scope, "<lambda>")
        with self._within(scope):
            self._bind_parameters(self._parameters(node.args))
            self.visit(node.body)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        enclosing = self.scope
        self._visit_all(node.decorator_list)
        header_scope = enclosing
        type_parameters = getattr(node, "type_params", [])
        if type_parameters:
            header_scope = self._child_scope(ScopeKind.TYPE_PARAMETERS, node, enclosing, node.name)
            header_scope.mangling_class = node.name
            self._visit_type_parameters(type_parameters, header_scope)
        with self._within(header_scope):
            self._visit_all(node.bases)
            for keyword in node.keywords:
                if keyword.arg is not None:
                    span = self._locate(name_locations.identifier_at_start, self.file.start_offset(keyword), keyword.arg)
                    self._add(OccurrenceRole.KEYWORD_ARGUMENT, span, keyword, "keyword", detail=None)
                self.visit(keyword.value)
        definition_span = self._locate(name_locations.definition_name, self.file.start_offset(node), "class", node.name)
        self._add(OccurrenceRole.DEFINITION, definition_span, node, "bind", lookup_scope=enclosing, name=node.name)
        class_scope = self._child_scope(ScopeKind.CLASS, node, header_scope, node.name)
        with self._within(class_scope):
            self._visit_all(node.body)

    def visit_TypeAlias(self, node: ast.TypeAlias) -> None:
        enclosing = self.scope
        header_scope = enclosing
        if node.type_params:
            header_scope = self._child_scope(ScopeKind.TYPE_PARAMETERS, node, enclosing, node.name.id)
            self._visit_type_parameters(node.type_params, header_scope)
        self._add(OccurrenceRole.DEFINITION, self._node_span(node.name), node.name, "bind", lookup_scope=enclosing)
        value_scope = self._child_scope(ScopeKind.TYPE_ALIAS_VALUE, node, header_scope, node.name.id)
        with self._within(value_scope):
            self.visit(node.value)

    def _visit_comprehension(self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp) -> None:
        self.visit(node.generators[0].iter)
        scope = self._child_scope(ScopeKind.COMPREHENSION, node, self.scope, "<comprehension>")
        with self._within(scope):
            for index, generator in enumerate(node.generators):
                if index > 0:
                    self.visit(generator.iter)
                self.visit(generator.target)
                self._visit_all(generator.ifs)
            if isinstance(node, ast.DictComp):
                self.visit(node.key)
                self.visit(node.value)
            else:
                self.visit(node.elt)

    visit_ListComp = _visit_comprehension
    visit_SetComp = _visit_comprehension
    visit_DictComp = _visit_comprehension
    visit_GeneratorExp = _visit_comprehension


class _FileResolver:
    """Resolves the names of one file to symbols using the scope rules of the Language Reference."""

    def __init__(self, file: SourceFile, walker: _FileScopeWalker) -> None:
        self.file = file
        self.walker = walker
        self.module_level_names: set[str] = set(walker.root.bound_names)
        for scope in walker.scopes:
            self.module_level_names |= scope.explicitly_global & scope.bound_names

    def local_symbol(self, scope: Scope, name: str) -> Symbol:
        return Symbol(SymbolKind.BINDING, self.file.module_key, scope.path, name)

    def global_symbol(self, name: str) -> Symbol:
        if name in self.module_level_names or name in _MODULE_IMPLICIT_NAMES:
            return Symbol(SymbolKind.BINDING, self.file.module_key, (), name)
        if hasattr(builtins, name):
            return Symbol(SymbolKind.BUILTIN, "", (), name)
        return Symbol(SymbolKind.UNRESOLVED_NAME, self.file.module_key, (), name)

    def _nonlocal_owner(self, scope: Scope, name: str) -> Scope:
        for enclosing in scope.enclosing_scopes():
            if enclosing.kind in (ScopeKind.CLASS, ScopeKind.MODULE):
                continue
            if name in enclosing.explicitly_nonlocal:
                continue
            if name in enclosing.bound_names and name not in enclosing.explicitly_global:
                return enclosing
        raise SemanticModelError(f"{self.file.path}: nonlocal {name} has no binding in an enclosing function.")

    def _free_lookup(self, scope: Scope, name: str) -> tuple[Symbol, tuple[Symbol, ...], str]:
        class_namespace_visible = scope.kind in _ANNOTATION_LIKE_KINDS
        enclosing = scope.parent
        while enclosing is not None and enclosing.kind is not ScopeKind.MODULE:
            if enclosing.kind is ScopeKind.CLASS:
                declared_elsewhere = name in enclosing.explicitly_global or name in enclosing.explicitly_nonlocal
                if class_namespace_visible and name in enclosing.bound_names and not declared_elsewhere:
                    outer, outer_alternatives, _ = self._free_lookup(enclosing, name)
                    return self.local_symbol(enclosing, name), (outer, *outer_alternatives), "free"
                if name == "__class__":
                    return self.local_symbol(enclosing, name), (), "free"
            elif name in enclosing.explicitly_global:
                return self.global_symbol(name), (), "global"
            elif name in enclosing.explicitly_nonlocal:
                pass
            elif name in enclosing.bound_names:
                return self.local_symbol(enclosing, name), (), "free"
            class_namespace_visible = class_namespace_visible and enclosing.kind in _ANNOTATION_LIKE_KINDS
            enclosing = enclosing.parent
        return self.global_symbol(name), (), "global"

    def resolve_load(self, scope: Scope, name: str) -> tuple[Symbol, tuple[Symbol, ...]]:
        symbol, alternatives, classification = self._resolve_load(scope, name)
        scope.classifications.setdefault(name, classification)
        return symbol, alternatives

    def _resolve_load(self, scope: Scope, name: str) -> tuple[Symbol, tuple[Symbol, ...], str]:
        if name in scope.explicitly_global:
            return self.global_symbol(name), (), "global"
        if name in scope.explicitly_nonlocal:
            return self.local_symbol(self._nonlocal_owner(scope, name), name), (), "free"
        if scope.kind is ScopeKind.MODULE:
            return self.global_symbol(name), (), "local"
        if scope.kind is ScopeKind.CLASS:
            if name in scope.bound_names:
                return self.local_symbol(scope, name), (self.global_symbol(name),), "local"
            if name in _CLASS_IMPLICIT_NAMES:
                return self.local_symbol(scope, name), (), "local"
            return self._free_lookup(scope, name)
        if name in scope.bound_names:
            return self.local_symbol(scope, name), (), "local"
        return self._free_lookup(scope, name)

    def resolve_binding(self, scope: Scope, name: str) -> Symbol:
        if name in scope.explicitly_global:
            scope.classifications.setdefault(name, "global")
            return self.global_symbol(name)
        if name in scope.explicitly_nonlocal:
            scope.classifications.setdefault(name, "free")
            return self.local_symbol(self._nonlocal_owner(scope, name), name)
        scope.classifications.setdefault(name, "local")
        return self.local_symbol(scope, name)


class _WorkspaceAnalyzer:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.walkers: dict[str, _FileScopeWalker] = {}
        self.resolvers: dict[str, _FileResolver] = {}
        self.known_module_names: set[str] = set()
        for module_name in workspace.modules:
            parts = module_name.split(".")
            for length in range(1, len(parts) + 1):
                self.known_module_names.add(".".join(parts[:length]))
        self.alias_of: dict[Symbol, Symbol] = {}
        self.occurrences_by_node_id: dict[str, dict[int, list[Occurrence]]] = {}
        self.attribute_symbols: dict[int, Symbol] = {}
        self.attribute_pendings: dict[int, _Pending] = {}
        self.binding_occurrences: dict[Symbol, list[Occurrence]] = {}
        self.final: dict[str, list[Occurrence]] = {}
        self.rebound_globals: set[Symbol] = set()
        self.modules_with_unknown_rebinding: set[str] = set()

    def analyze(self) -> WorkspaceBindings:
        for file in self.workspace.files.values():
            walker = _FileScopeWalker(file)
            walker.walk()
            self.walkers[file.path] = walker
            self.resolvers[file.path] = _FileResolver(file, walker)
        occurrences: dict[str, list[Occurrence]] = {path: [] for path in self.walkers}
        deferred: dict[str, list[_Pending]] = {path: [] for path in self.walkers}
        for path, walker in self.walkers.items():
            resolver = self.resolvers[path]
            for pending in walker.pending:
                if pending.resolution == "load":
                    symbol, alternatives = resolver.resolve_load(pending.scope, pending.name)
                    occurrences[path].append(self._occurrence(path, pending, symbol, alternatives))
                elif pending.resolution == "bind":
                    symbol = resolver.resolve_binding(pending.scope, pending.name)
                    occurrences[path].append(self._occurrence(path, pending, symbol, ()))
                else:
                    deferred[path].append(pending)
                    if pending.resolution == "attribute":
                        self.attribute_pendings[id(pending.node)] = pending
        for path, found in occurrences.items():
            self._index(path, found)
        self._compute_aliases()
        self._find_rebound_globals()
        for path, pendings in deferred.items():
            for pending in pendings:
                occurrence = self._resolve_deferred(path, pending)
                occurrences[path].append(occurrence)
                self._index(path, [occurrence])
        modules = {}
        for path, walker in self.walkers.items():
            file = self.workspace.files[path]
            self._check_scopes(file, walker)
            module_level_names = self.resolvers[path].module_level_names
            dynamic_uses = list(walker.dynamic_name_uses)
            dynamic_uses.extend(self._dynamic_uses_from_occurrences(path, occurrences[path]))
            modules[file.module_key] = ModuleBindings(
                file=file,
                root_scope=walker.root,
                scopes=walker.scopes,
                occurrences=sorted(occurrences[path], key=lambda o: (o.start_offset, o.end_offset, o.role.value)),
                module_level_names=module_level_names,
                dynamic_name_uses=dynamic_uses,
                has_module_getattr="__getattr__" in module_level_names,
                scope_by_node_id=walker.scope_by_node_id,
                occurrences_by_node_id=self.occurrences_by_node_id[path],
            )
        return WorkspaceBindings(
            self.workspace,
            modules,
            self.alias_of,
            frozenset(self.rebound_globals),
            frozenset(self.modules_with_unknown_rebinding),
        )

    def _occurrence(
        self, path: str, pending: _Pending, symbol: Symbol, alternatives: tuple[Symbol, ...]
    ) -> Occurrence:
        return Occurrence(
            file=path,
            start_offset=pending.start_offset,
            end_offset=pending.end_offset,
            source_name=pending.spelling,
            role=pending.role,
            scope=pending.scope,
            symbol=symbol,
            alternatives=alternatives,
            node=pending.node,
        )

    def _index(self, path: str, occurrences: list[Occurrence]) -> None:
        by_node = self.occurrences_by_node_id.setdefault(path, {})
        for occurrence in occurrences:
            by_node.setdefault(id(occurrence.node), []).append(occurrence)
            if occurrence.role in BINDING_ROLES:
                self.binding_occurrences.setdefault(occurrence.symbol, []).append(occurrence)

    def _check_scopes(self, file: SourceFile, walker: _FileScopeWalker) -> None:
        summaries = []
        for scope in walker.scopes:
            if scope.kind in (ScopeKind.FUNCTION, ScopeKind.LAMBDA, ScopeKind.CLASS):
                summaries.append(
                    ScopeSummary(
                        "class" if scope.kind is ScopeKind.CLASS else "function",
                        scope.display_name,
                        scope.node.lineno,  # type: ignore[attr-defined]
                        scope.classifications,
                    )
                )
        check_against_symtable(file.path, file.text, summaries)

    def _dynamic_uses_from_occurrences(self, path: str, occurrences: list[Occurrence]) -> list[DynamicNameUse]:
        uses = []
        for occurrence in occurrences:
            symbol = occurrence.symbol
            if (
                occurrence.role is OccurrenceRole.READ
                and symbol.kind is SymbolKind.BUILTIN
                and symbol.name in _DYNAMIC_BUILTINS
            ):
                uses.append(
                    DynamicNameUse(path, occurrence.start_offset, occurrence.end_offset, "dynamic-builtin", symbol.name)
                )
            if (
                occurrence.role in BINDING_ROLES
                and symbol.is_module_global
                and symbol.name == "__all__"
                and occurrence.scope.kind is ScopeKind.MODULE
            ):
                uses.append(DynamicNameUse(path, occurrence.start_offset, occurrence.end_offset, "dunder-all"))
        return uses

    def module_symbol(self, module: str) -> Symbol:
        if module in self.known_module_names:
            return Symbol(SymbolKind.MODULE, module, (), "")
        return Symbol(SymbolKind.EXTERNAL, module, (), "")

    def member_of_module(self, module: str, name: str) -> Symbol:
        defining_file = self.workspace.modules.get(module)
        if defining_file is not None and name in self.resolvers[defining_file.path].module_level_names:
            return Symbol(SymbolKind.BINDING, defining_file.module_key, (), name)
        if f"{module}.{name}" in self.known_module_names:
            return Symbol(SymbolKind.MODULE, f"{module}.{name}", (), "")
        if module in self.known_module_names:
            return Symbol(SymbolKind.UNRESOLVED_NAME, module, (), name)
        return Symbol(SymbolKind.EXTERNAL, module, (), name)

    def _compute_aliases(self) -> None:
        specs_by_symbol: dict[Symbol, list[_ImportAliasSpec]] = {}
        for path, walker in self.walkers.items():
            resolver = self.resolvers[path]
            for spec in walker.import_aliases:
                symbol = resolver.resolve_binding(spec.pending.scope, spec.pending.name)
                specs_by_symbol.setdefault(symbol, []).append(spec)
        for symbol, specs in specs_by_symbol.items():
            bindings = self.binding_occurrences.get(symbol, [])
            if len(bindings) != len(specs):
                continue
            targets = {self._alias_target(spec) for spec in specs}
            if len(targets) == 1:
                self.alias_of[symbol] = targets.pop()

    def _global_may_be_rebound(self, symbol: Symbol) -> bool:
        return symbol.is_module_global and (
            symbol in self.rebound_globals
            or "*" in self.modules_with_unknown_rebinding
            or symbol.module in self.modules_with_unknown_rebinding
        )

    def _module_named_by(self, path: str, expression: ast.AST) -> str | None:
        """The workspace module that an expression (a name bound by import, or a chain of attributes) denotes."""
        if not isinstance(expression, (ast.Name, ast.Attribute)):
            return None
        symbol = self._symbol_of_expression(path, expression)
        if symbol is None:
            return None
        origin = _follow_aliases(self.alias_of, symbol)
        return origin.module if origin.kind is SymbolKind.MODULE else None

    def _find_rebound_globals(self) -> None:
        """Finds module globals that code other than the module's own statements may rebind.

        Writes of `module.name`, `setattr(module, ...)`, and `delattr(module, ...)` rebind the global of that module;
        a module object that escapes as a value, or reflection that reaches namespaces, makes every global of the
        module (or of all modules) possibly rebound.
        """
        for path, walker in self.walkers.items():
            tree = walker.file.tree
            attribute_bases = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    self._note_attribute_rebinding(path, node)
                elif isinstance(node, ast.Name):
                    self._note_name_rebinding(path, node, id(node) in attribute_bases)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    imported = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module]
                    if "__main__" in imported:
                        self.modules_with_unknown_rebinding.add("*")

    def _note_attribute_rebinding(self, path: str, node: ast.Attribute) -> None:
        module = self._module_named_by(path, node.value)
        if isinstance(node.ctx, (ast.Store, ast.Del)) and module is not None:
            member = self.member_of_module(module, node.attr)
            if member.kind is SymbolKind.BINDING:
                self.rebound_globals.add(member)
        if node.attr in _NAMESPACE_REACHING_ATTRIBUTES:
            if module is not None and node.attr in ("__dict__", "__globals__"):
                self.modules_with_unknown_rebinding.add(module)
            elif node.attr not in ("__dict__", "__globals__"):
                self.modules_with_unknown_rebinding.add("*")
        if node.attr == "modules" and self._is_external_module(path, node.value, "sys"):
            self.modules_with_unknown_rebinding.add("*")

    def _is_external_module(self, path: str, expression: ast.AST, module_name: str) -> bool:
        if not isinstance(expression, ast.Name):
            return False
        symbol = self._symbol_of_expression(path, expression)
        if symbol is None:
            return False
        origin = _follow_aliases(self.alias_of, symbol)
        return origin.kind is SymbolKind.EXTERNAL and origin.name == "" and origin.module == module_name

    def _note_name_rebinding(self, path: str, node: ast.Name, is_attribute_base: bool) -> None:
        if not isinstance(node.ctx, ast.Load):
            return
        occurrences = self.occurrences_by_node_id[path].get(id(node), [])
        if not occurrences:
            return
        symbol = occurrences[0].symbol
        origin = _follow_aliases(self.alias_of, symbol)
        if origin.kind is SymbolKind.MODULE and not is_attribute_base:
            self.modules_with_unknown_rebinding.add(origin.module)
        if origin.kind is SymbolKind.EXTERNAL and origin.module == "builtins" and origin.name in _NAMESPACE_BUILTINS:
            symbol = Symbol(SymbolKind.BUILTIN, "", (), origin.name)
        if symbol.kind is SymbolKind.BUILTIN and symbol.name in _NAMESPACE_BUILTINS:
            if symbol.name in _EVERYWHERE_NAMESPACE_BUILTINS:
                self.modules_with_unknown_rebinding.add("*")
            else:
                self.modules_with_unknown_rebinding.add(self.workspace.files[path].module_key)
        if origin.kind is SymbolKind.EXTERNAL and origin.module == "importlib" and origin.name == "import_module":
            self.modules_with_unknown_rebinding.add("*")

    def _alias_target(self, spec: _ImportAliasSpec) -> Symbol:
        if spec.member is None:
            return self.module_symbol(spec.module)
        return self.member_of_module(spec.module, spec.member)

    def _resolve_deferred(self, path: str, pending: _Pending) -> Occurrence:
        if pending.resolution == "import-source":
            module, name = pending.detail
            return self._occurrence(path, pending, self.member_of_module(module, name), ())
        if pending.resolution == "attribute":
            return self._occurrence(path, pending, self._attribute_symbol(path, pending), ())
        return self._occurrence(path, pending, self._keyword_symbol(path, pending), ())

    def _symbol_of_expression(self, path: str, expression: ast.AST) -> Symbol | None:
        if isinstance(expression, ast.Name):
            for occurrence in self.occurrences_by_node_id[path].get(id(expression), []):
                return occurrence.symbol
        if isinstance(expression, ast.Attribute):
            return self._attribute_symbol(path, self.attribute_pendings[id(expression)])
        return None

    def _attribute_symbol(self, path: str, pending: _Pending) -> Symbol:
        known = self.attribute_symbols.get(id(pending))
        if known is not None:
            return known
        value_symbol = self._symbol_of_expression(path, pending.detail)
        symbol = Symbol(SymbolKind.ATTRIBUTE, "", (), pending.name)
        if value_symbol is not None:
            origin = _follow_aliases(self.alias_of, value_symbol)
            if origin.kind is SymbolKind.MODULE:
                symbol = self.member_of_module(origin.module, pending.name)
        self.attribute_symbols[id(pending)] = symbol
        return symbol

    def _keyword_symbol(self, path: str, pending: _Pending) -> Symbol:
        unknown = Symbol(SymbolKind.KEYWORD_OF_UNKNOWN_CALLEE, "", (), pending.name)
        if pending.detail is None:
            return unknown
        callee_symbol = self._symbol_of_expression(path, pending.detail)
        if callee_symbol is None:
            return unknown
        origin = _follow_aliases(self.alias_of, callee_symbol)
        if origin.kind is SymbolKind.BUILTIN:
            return Symbol(SymbolKind.KEYWORD_OF_BUILTIN, "", (), pending.name)
        if origin.kind is not SymbolKind.BINDING:
            return unknown
        definitions = self.binding_occurrences.get(origin, [])
        if len(definitions) != 1 or definitions[0].role is not OccurrenceRole.DEFINITION:
            return unknown
        if self._global_may_be_rebound(origin):
            return unknown
        function = definitions[0].node
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) or function.decorator_list:
            return unknown
        function_scope = self.walkers[definitions[0].file].scope_by_node_id[id(function)]
        for parameter in [*function.args.args, *function.args.kwonlyargs]:
            if mangled_name(parameter.arg, function_scope.mangling_class) == pending.name:
                return Symbol(SymbolKind.BINDING, origin.module, function_scope.path, pending.name)
        return unknown
