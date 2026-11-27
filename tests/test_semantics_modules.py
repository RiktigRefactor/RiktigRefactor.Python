"""Cross-module bindings, aliases, attribute access on modules, keyword arguments, and dynamic name uses."""

import pytest

from riktigrefactor.semantics import OccurrenceRole as Role
from riktigrefactor.semantics import SymbolKind
from semantics_helpers import (
    analyze_files,
    analyze_source,
    analyze_sources,
    is_module_global,
    occurrence,
    occurrences_named,
    symbol_of,
)


def test_from_import_name_refers_to_the_symbol_in_the_other_module():
    bindings = analyze_sources(
        lib="""
        def helper(): ...
        """,
        main="""
        from lib import helper
        helper()
        """,
    )
    source_name = occurrences_named(bindings, "helper", Role.IMPORT_SOURCE_NAME)[0]
    local_binding = occurrences_named(bindings, "helper", Role.IMPORT_BINDING)[0]
    definition = occurrence(bindings, "helper", 0, Role.DEFINITION, "lib.py")
    assert source_name.symbol == definition.symbol
    assert source_name.span == local_binding.span
    assert is_module_global(local_binding.symbol, "helper", "main")
    assert bindings.origin_of(local_binding.symbol) == definition.symbol
    use = occurrences_named(bindings, "helper", Role.READ)[0]
    assert bindings.origin_of(use.symbol) == definition.symbol


def test_from_import_with_as_binds_the_alias_name():
    bindings = analyze_sources(
        lib="value = 1\n",
        main="""
        from lib import value as v
        print(v)
        """,
    )
    alias = occurrences_named(bindings, "v", Role.IMPORT_BINDING)[0]
    source_name = occurrences_named(bindings, "value", Role.IMPORT_SOURCE_NAME)[0]
    assert alias.span != source_name.span
    assert bindings.origin_of(alias.symbol) == symbol_of(bindings, "value", 0, path="lib.py")


def test_import_module_attribute_access_resolves_to_the_module_symbol():
    bindings = analyze_sources(
        lib="""
        x = 1
        def f(a): ...
        """,
        main="""
        import lib
        print(lib.x, lib.f(a=1))
        """,
    )
    attribute = occurrences_named(bindings, "x", Role.ATTRIBUTE_READ)[0]
    assert attribute.symbol == symbol_of(bindings, "x", 0, path="lib.py")
    keyword = occurrences_named(bindings, "a", Role.KEYWORD_ARGUMENT)[0]
    assert keyword.symbol == occurrence(bindings, "a", 0, Role.PARAMETER, "lib.py").symbol


def test_import_module_as_alias_and_nested_attribute_chain():
    bindings = analyze_files(
        {
            "pkg/__init__.py": "",
            "pkg/inner.py": "def deep(): ...\n",
            "main.py": """
            import pkg.inner as k
            import pkg.inner
            k.deep()
            pkg.inner.deep()
            """,
        }
    )
    definition = occurrence(bindings, "deep", 0, Role.DEFINITION, "pkg/inner.py").symbol
    reads = occurrences_named(bindings, "deep", Role.ATTRIBUTE_READ)
    assert [r.symbol for r in reads] == [definition, definition]


def test_two_imports_of_different_modules_under_one_name_are_not_an_alias():
    bindings = analyze_sources(
        a="x = 1\n",
        b="x = 2\n",
        main="""
        try:
            from a import x
        except ImportError:
            from b import x
        print(x)
        """,
    )
    use = occurrences_named(bindings, "x", Role.READ)[0]
    assert bindings.origin_of(use.symbol) == use.symbol
    sources = occurrences_named(bindings, "x", Role.IMPORT_SOURCE_NAME)
    assert {s.symbol.module for s in sources} == {"a", "b"}


def test_name_bound_by_import_and_assignment_is_not_an_alias():
    bindings = analyze_sources(
        lib="x = 1\n",
        main="""
        from lib import x
        x = 2
        """,
    )
    assert not bindings.is_alias(symbol_of(bindings, "x", 0, Role.IMPORT_BINDING))


def test_relative_imports_in_packages():
    bindings = analyze_files(
        {
            "pkg/__init__.py": "",
            "pkg/a.py": "value = 1\n",
            "pkg/b.py": """
            from .a import value
            from . import a
            print(value, a.value)
            """,
            "pkg/sub/__init__.py": "from ..a import value as parent_value\n",
        }
    )
    definition = symbol_of(bindings, "value", 0, path="pkg/a.py")
    assert occurrence(bindings, "value", 0, Role.IMPORT_SOURCE_NAME, "pkg/b.py").symbol == definition
    assert occurrences_named(bindings, "value", Role.ATTRIBUTE_READ, "pkg/b.py")[0].symbol == definition
    assert occurrences_named(bindings, "value", Role.IMPORT_SOURCE_NAME, "pkg/sub/__init__.py")[0].symbol == definition


def test_from_package_import_submodule_gives_module_symbol():
    bindings = analyze_files(
        {
            "pkg/__init__.py": "",
            "pkg/sub.py": "def f(): ...\n",
            "main.py": """
            from pkg import sub
            sub.f()
            """,
        }
    )
    assert symbol_of(bindings, "sub", 0, Role.IMPORT_SOURCE_NAME).kind is SymbolKind.MODULE
    assert occurrences_named(bindings, "f", Role.ATTRIBUTE_READ)[0].symbol == symbol_of(
        bindings, "f", 0, path="pkg/sub.py"
    )


def test_src_layout_modules_are_named_without_src():
    bindings = analyze_files(
        {"src/app/core.py": "def f(): ...\n", "main.py": "from app.core import f\n"}
    )
    assert occurrence(bindings, "f", 0, Role.IMPORT_SOURCE_NAME).symbol == symbol_of(
        bindings, "f", 0, path="src/app/core.py"
    )


def test_import_from_outside_the_workspace_is_external():
    bindings = analyze_source(
        """
        import os
        from json import dumps
        os.getcwd()
        dumps({})
        """
    )
    assert symbol_of(bindings, "dumps", 0, Role.IMPORT_SOURCE_NAME).kind is SymbolKind.EXTERNAL
    assert bindings.origin_of(symbol_of(bindings, "os", 0)).kind is SymbolKind.EXTERNAL
    assert symbol_of(bindings, "getcwd").kind is SymbolKind.ATTRIBUTE


def test_attribute_of_an_object_is_an_attribute_symbol_shared_by_spelling():
    bindings = analyze_source(
        """
        class C:
            def m(self):
                self.value = 1
        c = C()
        print(c.value)
        """
    )
    assert symbol_of(bindings, "value", 0).kind is SymbolKind.ATTRIBUTE
    assert symbol_of(bindings, "value", 0) == symbol_of(bindings, "value", 1)
    assert occurrences_named(bindings, "value")[0].role is Role.ATTRIBUTE_WRITE


def test_member_missing_from_workspace_module_is_unresolved_name():
    bindings = analyze_sources(lib="x = 1\n", main="import lib\nlib.missing\n")
    assert symbol_of(bindings, "missing").kind is SymbolKind.UNRESOLVED_NAME


def test_keyword_of_builtin_and_of_unknown_callee():
    bindings = analyze_source(
        """
        def local(a): ...
        print(1, end="")
        local(a=1)
        something.method(a=1)
        undefined_function(b=2)
        """
    )
    assert symbol_of(bindings, "end").kind is SymbolKind.KEYWORD_OF_BUILTIN
    assert symbol_of(bindings, "a", 0, Role.KEYWORD_ARGUMENT).kind is SymbolKind.BINDING
    assert symbol_of(bindings, "a", 1, Role.KEYWORD_ARGUMENT).kind is SymbolKind.KEYWORD_OF_UNKNOWN_CALLEE
    assert symbol_of(bindings, "b").kind is SymbolKind.KEYWORD_OF_UNKNOWN_CALLEE


def test_keyword_of_decorated_or_reassigned_function_is_unknown():
    bindings = analyze_source(
        """
        import functools
        @functools.cache
        def decorated(a): ...
        def reassigned(a): ...
        reassigned = print
        decorated(a=1)
        reassigned(a=1)
        """
    )
    kinds = [o.symbol.kind for o in occurrences_named(bindings, "a", Role.KEYWORD_ARGUMENT)]
    assert kinds == [SymbolKind.KEYWORD_OF_UNKNOWN_CALLEE] * 2


def test_positional_only_parameter_is_not_matched_by_keyword():
    bindings = analyze_source(
        """
        def f(a, /, **rest): ...
        f(a=1)
        """
    )
    assert symbol_of(bindings, "a", 1).kind is SymbolKind.KEYWORD_OF_UNKNOWN_CALLEE


def test_dynamic_name_uses_are_reported():
    bindings = analyze_sources(
        lib="x = 1\n",
        main="""
        from lib import *
        __all__ = ["x"]
        eval("x")
        getattr(object(), "x")
        def f(**kw): ...
        f(**{"a": 1})
        print(globals().__class__.__dict__)
        """,
    )
    kinds = sorted((use.kind, use.detail) for use in bindings.dynamic_name_uses())
    assert ("star-import", "lib") in kinds
    assert ("dunder-all", "") in kinds
    assert ("dynamic-builtin", "eval") in kinds
    assert ("dynamic-builtin", "getattr") in kinds
    assert ("dynamic-builtin", "globals") in kinds
    assert ("keyword-unpacking-call", "f") in kinds
    assert ("dunder-dict", "") in kinds


def test_occurrences_with_origin_collects_references_through_aliases():
    bindings = analyze_sources(
        lib="""
        def f(): ...
        """,
        mid="""
        from lib import f
        """,
        main="""
        from mid import f
        import lib
        f()
        lib.f()
        """,
    )
    origin = symbol_of(bindings, "f", 0, Role.DEFINITION, "lib.py")
    found = {(o.file, o.role) for o in bindings.occurrences_with_origin(origin)}
    assert ("main.py", Role.READ) in found
    assert ("main.py", Role.ATTRIBUTE_READ) in found
    assert ("mid.py", Role.IMPORT_SOURCE_NAME) in found
    assert ("main.py", Role.IMPORT_SOURCE_NAME) in found


def test_cursor_lookup_prefers_the_occurrence_containing_the_offset():
    bindings = analyze_source("alpha = 1\nprint(alpha)\n")
    offset = bindings.workspace.files["main.py"].text.index("alpha", 5)
    assert [o.role for o in bindings.occurrences_at_cursor("main.py", offset + 2)] == [Role.READ]
    assert [o.role for o in bindings.occurrences_at_cursor("main.py", offset + 5)] == [Role.READ]
    assert bindings.occurrences_at_cursor("main.py", offset + 6) == []


def test_non_ascii_identifiers_have_exact_spans():
    bindings = analyze_source(
        """
        héllo = "é😀"
        def wörld(ünï=héllo): return ünï + "😀"
        print(héllo, wörld())
        """
    )
    source = bindings.workspace.files["main.py"].text
    for found in bindings.occurrences:
        assert source[found.start_offset : found.end_offset] == found.source_name
    assert len(occurrences_named(bindings, "héllo")) == 3


def test_identifiers_with_nfkc_forms_use_the_normalized_name_and_source_spelling():
    bindings = analyze_source("ｘ = 1\nprint(x)\n")
    first = occurrences_named(bindings, "ｘ", Role.WRITE)[0]
    assert first.symbol.name == "x"
    assert first.end_offset - first.start_offset == 1
    assert symbol_of(bindings, "x", 0, Role.READ) == first.symbol


def test_modules_with_the_same_dotted_name_are_ambiguous():
    from riktigrefactor.protocol import RefusalError

    with pytest.raises(RefusalError) as refusal:
        analyze_files({"src/a.py": "x = 1\n", "a.py": "x = 2\n"})
    assert refusal.value.code == "ambiguous-module-name"
