"""Helpers for tests of the binding model."""

import textwrap

from riktigrefactor.semantics import (
    Occurrence,
    OccurrenceRole,
    Symbol,
    SymbolKind,
    WorkspaceBindings,
    analyze_workspace,
)
from riktigrefactor.workspace import Workspace


def analyze_files(files: dict[str, str]) -> WorkspaceBindings:
    texts = {path: textwrap.dedent(text).lstrip("\n") for path, text in files.items()}
    return analyze_workspace(Workspace.from_texts("/workspace", texts))


def analyze_sources(**sources: str) -> WorkspaceBindings:
    """Keyword names are top-level module names; use analyze_files for packages."""
    return analyze_files({name + ".py": text for name, text in sources.items()})


def analyze_source(text: str) -> WorkspaceBindings:
    return analyze_sources(main=text)


def occurrences_named(
    bindings: WorkspaceBindings, name: str, role: OccurrenceRole | None = None, path: str = "main.py"
) -> list[Occurrence]:
    return [
        o
        for o in bindings.occurrences_in_file(path)
        if o.source_name == name and (role is None or o.role is role)
    ]


def occurrence(
    bindings: WorkspaceBindings, name: str, nth: int = 0, role: OccurrenceRole | None = None, path: str = "main.py"
) -> Occurrence:
    return occurrences_named(bindings, name, role, path)[nth]


def symbol_of(bindings: WorkspaceBindings, name: str, nth: int = 0, role=None, path: str = "main.py") -> Symbol:
    return occurrence(bindings, name, nth, role, path).symbol


def scope_kinds(symbol: Symbol) -> tuple[str, ...]:
    return tuple(key.kind.value for key in symbol.scope)


def is_module_global(symbol: Symbol, name: str, module: str = "main") -> bool:
    return symbol.kind is SymbolKind.BINDING and symbol.scope == () and symbol.name == name and symbol.module == module
