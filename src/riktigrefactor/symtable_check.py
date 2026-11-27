"""Cross-checks our scope analysis against CPython's own `symtable` (a safety net, not the source of truth).

For every function, lambda, and class scope that we can pair with a `symtable` table, each name we classified
as local, global, or free must be classified the same way by `symtable`.
Comprehension scopes are not compared: since Python 3.12 they are inlined into their parent's table.
"""

import symtable
from dataclasses import dataclass

from riktigrefactor.protocol import SemanticModelError

_COMPREHENSION_TABLE_NAMES = {"listcomp", "setcomp", "dictcomp", "genexp"}
_INTERNAL_NAME_PREFIXES = (".",)
_IMPLICIT_NAMES = {
    "__class__",
    "__classdict__",
    "__module__",
    "__qualname__",
    "__firstlineno__",
    "__static_attributes__",
    "__type_params__",
    "__annotations__",
    "__annotate__",
    "__conditional_annotations__",
}


@dataclass(frozen=True)
class ScopeSummary:
    """What our analysis decided for one scope; `classifications` maps a name to "local", "global", or "free"."""

    symtable_type: str
    name: str
    line: int
    classifications: dict[str, str]


def _flatten(table: symtable.SymbolTable) -> list[symtable.SymbolTable]:
    flattened = []
    for child in table.get_children():
        flattened.append(child)
        flattened.extend(_flatten(child))
    return flattened


def _classification_of(symbol: symtable.Symbol) -> str:
    """Uses is_declared_global and is_local instead of is_global, which treats every function named "top" as the module."""
    if symbol.is_free():
        return "free"
    if symbol.is_declared_global():
        return "global"
    if symbol.is_local():
        return "local"
    return "global"


def check_against_symtable(path: str, text: str, summaries: list[ScopeSummary]) -> None:
    try:
        root = symtable.symtable(text, path, "exec")
    except SyntaxError as error:
        raise SemanticModelError(f"{path}: the symbol table cannot be built: {error}") from error
    tables_by_key: dict[tuple[str, str, int], list[symtable.SymbolTable]] = {}
    for table in _flatten(root):
        table_type = table.get_type()
        if table_type not in ("function", "class"):
            continue
        name = table.get_name()
        if table_type == "function" and name in _COMPREHENSION_TABLE_NAMES:
            continue
        if name == "lambda":
            name = "<lambda>"
        tables_by_key.setdefault((table_type, name, table.get_lineno()), []).append(table)
    summaries_by_key: dict[tuple[str, str, int], list[ScopeSummary]] = {}
    for summary in summaries:
        summaries_by_key.setdefault((summary.symtable_type, summary.name, summary.line), []).append(summary)
    for key, group in summaries_by_key.items():
        tables = tables_by_key.get(key, [])
        if len(tables) != len(group):
            continue
        for summary, table in zip(group, tables, strict=True):
            _compare(path, summary, table)


def _compare(path: str, summary: ScopeSummary, table: symtable.SymbolTable) -> None:
    for name, ours in summary.classifications.items():
        if name in _IMPLICIT_NAMES or name.startswith(_INTERNAL_NAME_PREFIXES):
            continue
        try:
            symbol = table.lookup(name)
        except KeyError:
            continue
        theirs = _classification_of(symbol)
        if ours != theirs:
            raise SemanticModelError(
                f"{path}: line {summary.line}: we classify {name} in {summary.name} as {ours}, "
                f"but Python's symbol table says {theirs}."
            )
