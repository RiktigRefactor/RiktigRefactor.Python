"""The binding model follows the scope rules of the Language Reference, "Naming and binding"."""

import pytest

from riktigrefactor.semantics import OccurrenceRole as Role
from riktigrefactor.semantics import SemanticModelError, SymbolKind
from semantics_helpers import (
    analyze_source,
    is_module_global,
    occurrence,
    occurrences_named,
    scope_kinds,
    symbol_of,
)


def test_module_global_read_in_function_binds_module_symbol():
    bindings = analyze_source(
        """
        x = 1
        def f():
            return x
        """
    )
    assert symbol_of(bindings, "x", 1) == symbol_of(bindings, "x", 0)
    assert is_module_global(symbol_of(bindings, "x", 1), "x")


def test_assignment_in_function_makes_a_local_that_shadows_the_global():
    bindings = analyze_source(
        """
        x = 1
        def f():
            x = 2
            return x
        """
    )
    local_write, local_read = symbol_of(bindings, "x", 1), symbol_of(bindings, "x", 2)
    assert local_write == local_read
    assert scope_kinds(local_write) == ("function",)
    assert local_write != symbol_of(bindings, "x", 0)


def test_read_before_assignment_in_function_is_still_the_local():
    bindings = analyze_source(
        """
        x = 1
        def f():
            print(x)
            x = 2
        """
    )
    assert scope_kinds(symbol_of(bindings, "x", 1)) == ("function",)


def test_parameter_shadows_global_and_defaults_are_evaluated_outside():
    bindings = analyze_source(
        """
        a = 1
        def f(a=a):
            return a
        """
    )
    default, body_read = occurrences_named(bindings, "a", Role.READ)
    parameter = occurrences_named(bindings, "a", Role.PARAMETER)[0]
    assert is_module_global(default.symbol, "a")
    assert scope_kinds(parameter.symbol) == ("function",)
    assert body_read.symbol == parameter.symbol


def test_decorators_and_annotations_are_evaluated_in_the_enclosing_scope():
    bindings = analyze_source(
        """
        def deco(f): return f
        T = int
        def outer():
            deco = 1
            @deco
            def inner(x: T): pass
        """
    )
    deco_use = occurrences_named(bindings, "deco", Role.READ)[0]
    assert scope_kinds(deco_use.symbol) == ("function",)
    assert is_module_global(occurrences_named(bindings, "T", Role.READ)[0].symbol, "T")


def test_nested_function_reads_enclosing_function_local_as_free_variable():
    bindings = analyze_source(
        """
        def outer():
            count = 0
            def inner():
                return count
            return inner
        """
    )
    assert symbol_of(bindings, "count", 1) == symbol_of(bindings, "count", 0)
    assert scope_kinds(symbol_of(bindings, "count", 1)) == ("function",)


def test_nonlocal_assignment_binds_the_enclosing_function_local():
    bindings = analyze_source(
        """
        def outer():
            count = 0
            def inner():
                nonlocal count
                count = count + 1
            return inner
        """
    )
    outer_symbol = symbol_of(bindings, "count", 0)
    assert all(o.symbol == outer_symbol for o in occurrences_named(bindings, "count"))


def test_global_statement_binds_module_symbol_even_if_module_never_assigns_it():
    bindings = analyze_source(
        """
        def f():
            global created
            created = 1
        def g():
            return created
        """
    )
    assert all(is_module_global(o.symbol, "created") for o in occurrences_named(bindings, "created"))


def test_global_declared_name_that_module_also_assigns_is_one_symbol():
    bindings = analyze_source(
        """
        n = 0
        def f():
            global n
            n += 1
        """
    )
    assert len({o.symbol for o in occurrences_named(bindings, "n")}) == 1


def test_builtin_is_builtin_unless_shadowed():
    bindings = analyze_source(
        """
        print(len([]))
        def f(len):
            return len
        """
    )
    assert symbol_of(bindings, "len", 0).kind is SymbolKind.BUILTIN
    assert symbol_of(bindings, "len", 2).kind is SymbolKind.BINDING


def test_module_level_name_shadows_builtin():
    bindings = analyze_source(
        """
        def f():
            return sum
        sum = 3
        """
    )
    assert is_module_global(symbol_of(bindings, "sum", 0), "sum")


def test_undefined_global_name_is_unresolved():
    bindings = analyze_source("print(undefined_name)\n")
    assert symbol_of(bindings, "undefined_name").kind is SymbolKind.UNRESOLVED_NAME


def test_class_body_names_are_not_visible_in_methods():
    bindings = analyze_source(
        """
        x = "global"
        class C:
            x = "class"
            def method(self):
                return x
        """
    )
    assert is_module_global(symbol_of(bindings, "x", 2), "x")
    class_x = symbol_of(bindings, "x", 1)
    assert scope_kinds(class_x) == ("class",)


def test_class_body_read_of_class_local_may_fall_back_to_global():
    bindings = analyze_source(
        """
        x = "global"
        class C:
            y = x
            x = 1
        """
    )
    read = occurrences_named(bindings, "x", Role.READ)[0]
    assert scope_kinds(read.symbol) == ("class",)
    assert [is_module_global(a, "x") for a in read.alternatives] == [True]


def test_class_body_does_not_see_enclosing_function_local_when_it_assigns_the_name():
    bindings = analyze_source(
        """
        def f():
            x = 1
            class C:
                x = x
        """
    )
    read = occurrences_named(bindings, "x", Role.READ)[0]
    assert scope_kinds(read.symbol) == ("function", "class")
    assert all(a.scope == () for a in read.alternatives)


def test_class_body_reads_enclosing_function_local_when_it_does_not_assign_the_name():
    bindings = analyze_source(
        """
        def f():
            x = 1
            class C:
                y = x
        """
    )
    assert scope_kinds(occurrences_named(bindings, "x", Role.READ)[0].symbol) == ("function",)


def test_dunder_class_in_method_binds_the_class_scope():
    bindings = analyze_source(
        """
        class C:
            def method(self):
                return __class__
        """
    )
    assert scope_kinds(symbol_of(bindings, "__class__")) == ("class",)


def test_comprehension_target_is_local_to_the_comprehension():
    bindings = analyze_source(
        """
        i = "outer"
        values = [i for i in range(3)]
        print(i)
        """
    )
    assert scope_kinds(symbol_of(bindings, "i", 1)) == ("comprehension",)
    assert symbol_of(bindings, "i", 1) == symbol_of(bindings, "i", 2)
    assert is_module_global(symbol_of(bindings, "i", 3), "i")


def test_first_iterable_of_comprehension_is_evaluated_in_the_enclosing_scope():
    bindings = analyze_source(
        """
        def f(items):
            return [items for items in items]
        """
    )
    iterable = occurrences_named(bindings, "items", Role.READ)
    element, first_iterable = iterable
    assert scope_kinds(element.symbol) == ("function", "comprehension")
    assert scope_kinds(first_iterable.symbol) == ("function",)


def test_second_iterable_of_comprehension_is_evaluated_inside_it():
    bindings = analyze_source(
        """
        def f(rows):
            return [x for row in rows for x in row]
        """
    )
    assert scope_kinds(symbol_of(bindings, "row", 1)) == ("function", "comprehension")


def test_comprehension_in_class_body_does_not_see_class_names_but_first_iterable_does():
    bindings = analyze_source(
        """
        names = ["global"]
        class C:
            names = ["a", "b"]
            copies = [n for n in names]
            other = [names for _ in range(2)]
        """
    )
    first_iterable = occurrences_named(bindings, "names", Role.READ)[0]
    inside = occurrences_named(bindings, "names", Role.READ)[1]
    assert scope_kinds(first_iterable.symbol) == ("class",)
    assert is_module_global(inside.symbol, "names")


def test_walrus_in_comprehension_binds_the_enclosing_function():
    bindings = analyze_source(
        """
        def f(data):
            found = [y for x in data if (y := x)]
            return y
        """
    )
    walrus_target = occurrences_named(bindings, "y", Role.WRITE)[0]
    assert scope_kinds(walrus_target.symbol) == ("function",)
    assert symbol_of(bindings, "y", 2) == walrus_target.symbol


def test_walrus_in_nested_comprehensions_binds_the_nearest_non_comprehension_scope():
    bindings = analyze_source(
        """
        def f(data):
            return [[(z := a) for a in row] for row in data], z
        """
    )
    walrus_target = occurrences_named(bindings, "z", Role.WRITE)[0]
    assert scope_kinds(walrus_target.symbol) == ("function",)
    assert occurrences_named(bindings, "z", Role.READ)[0].symbol == walrus_target.symbol


def test_walrus_at_module_level_in_comprehension_binds_module_symbol():
    bindings = analyze_source("values = [(w := v) for v in range(2)]\nprint(w)\n")
    assert is_module_global(occurrences_named(bindings, "w", Role.WRITE)[0].symbol, "w")


def test_lambda_parameters_are_local_and_body_reads_enclosing_locals():
    bindings = analyze_source(
        """
        def f(a):
            return lambda b: a + b
        """
    )
    assert scope_kinds(symbol_of(bindings, "b", 1)) == ("function", "lambda")
    assert scope_kinds(occurrences_named(bindings, "a", Role.READ)[0].symbol) == ("function",)


def test_lambda_default_is_evaluated_in_the_enclosing_scope():
    bindings = analyze_source(
        """
        n = 5
        g = lambda n=n: n
        """
    )
    default = occurrences_named(bindings, "n", Role.READ)[0]
    assert is_module_global(default.symbol, "n")


def test_type_parameters_of_generic_function_are_visible_in_annotations_and_body():
    bindings = analyze_source(
        """
        def first[T](items: list[T]) -> T:
            value: T = items[0]
            return value
        """
    )
    parameter = occurrences_named(bindings, "T", Role.TYPE_PARAMETER)[0]
    assert scope_kinds(parameter.symbol) == ("type-parameters",)
    uses = occurrences_named(bindings, "T", Role.READ)
    assert len(uses) == 3
    assert all(use.symbol == parameter.symbol for use in uses)


def test_generic_class_type_parameters_are_visible_in_bases_and_methods():
    bindings = analyze_source(
        """
        class Box[T](list[T]):
            def get(self) -> T: ...
        """
    )
    parameter = occurrences_named(bindings, "T", Role.TYPE_PARAMETER)[0]
    assert all(use.symbol == parameter.symbol for use in occurrences_named(bindings, "T", Role.READ))


def test_type_alias_value_sees_its_type_parameters_and_module_names():
    bindings = analyze_source(
        """
        Number = int
        type Pair[A] = tuple[A, Number]
        """
    )
    parameter = occurrences_named(bindings, "A", Role.TYPE_PARAMETER)[0]
    assert occurrences_named(bindings, "A", Role.READ)[0].symbol == parameter.symbol
    assert is_module_global(occurrences_named(bindings, "Number", Role.READ)[0].symbol, "Number")
    assert is_module_global(occurrences_named(bindings, "Pair", Role.DEFINITION)[0].symbol, "Pair")


def test_type_parameter_does_not_leak_into_the_enclosing_scope():
    bindings = analyze_source(
        """
        T = "module"
        def f[T](x: T): ...
        print(T)
        """
    )
    assert is_module_global(occurrences_named(bindings, "T", Role.READ)[-1].symbol, "T")


def test_generic_method_annotation_can_see_class_namespace():
    bindings = analyze_source(
        """
        class C:
            Alias = int
            def method[T](self, x: Alias) -> T: ...
        """
    )
    alias_use = occurrences_named(bindings, "Alias", Role.READ)[0]
    assert scope_kinds(alias_use.symbol) == ("class",)


def test_match_captures_bind_in_the_enclosing_scope():
    bindings = analyze_source(
        """
        def f(command):
            match command:
                case [first, *rest]:
                    return first, rest
                case {"key": value, **others}:
                    return value, others
                case str() as text:
                    return text
        """
    )
    for name in ["first", "rest", "value", "others", "text"]:
        captured = occurrences_named(bindings, name, Role.MATCH_CAPTURE)[0]
        assert scope_kinds(captured.symbol) == ("function",)
        assert occurrences_named(bindings, name, Role.READ)[0].symbol == captured.symbol
        assert captured.source_name == name


def test_except_as_binds_the_name_in_the_scope():
    bindings = analyze_source(
        """
        def f():
            try:
                pass
            except (ValueError, KeyError) as error:
                return error
        """
    )
    target = occurrences_named(bindings, "error", Role.EXCEPT_NAME)[0]
    assert scope_kinds(target.symbol) == ("function",)
    assert occurrences_named(bindings, "error", Role.READ)[0].symbol == target.symbol


def test_del_makes_the_name_local():
    bindings = analyze_source(
        """
        x = 1
        def f():
            del x
        """
    )
    assert scope_kinds(occurrences_named(bindings, "x", Role.DELETE)[0].symbol) == ("function",)


def test_annotation_without_value_makes_the_name_local():
    bindings = analyze_source(
        """
        x = 1
        def f():
            x: int
            return x
        """
    )
    assert scope_kinds(occurrences_named(bindings, "x", Role.ANNOTATION_ONLY)[0].symbol) == ("function",)
    assert scope_kinds(occurrences_named(bindings, "x", Role.READ)[0].symbol) == ("function",)


def test_augmented_assignment_target_is_both_a_local_binding_and_marked():
    bindings = analyze_source(
        """
        n = 0
        def f():
            n += 1
        """
    )
    assert occurrences_named(bindings, "n", Role.AUGMENTED_WRITE)[0].symbol.scope != ()


def test_for_with_and_import_targets_bind_locals():
    bindings = analyze_source(
        """
        def f(path):
            import os.path as osp
            for item in path:
                with open(item) as handle:
                    print(handle, osp)
        """
    )
    for name in ["item", "handle", "osp"]:
        assert scope_kinds(symbol_of(bindings, name, 0)) == ("function",)


def test_private_names_are_mangled_inside_classes():
    bindings = analyze_source(
        """
        class Thing:
            def method(self):
                __secret = 1
                return __secret
        __secret = 2
        """
    )
    first = symbol_of(bindings, "__secret", 0)
    assert first.name == "_Thing__secret"
    assert symbol_of(bindings, "__secret", 1) == first
    assert symbol_of(bindings, "__secret", 2).name == "__secret"
    assert occurrence(bindings, "__secret", 0).source_name == "__secret"


def test_dunder_names_are_not_mangled():
    bindings = analyze_source(
        """
        class Thing:
            def __init__(self): ...
        """
    )
    assert symbol_of(bindings, "__init__").name == "__init__"


def test_async_constructs():
    bindings = analyze_source(
        """
        async def f(source):
            return [x async for x in source if await x]
        """
    )
    assert scope_kinds(symbol_of(bindings, "x", 0)) == ("function", "comprehension")


def test_nonlocal_without_enclosing_binding_is_a_semantic_model_error():
    with pytest.raises(SemanticModelError):
        analyze_source(
            """
            def f():
                def g():
                    nonlocal missing
            """
        )


def test_global_and_nonlocal_declarations_are_occurrences_with_exact_spans():
    bindings = analyze_source(
        """
        def f():
            global alpha, beta  # comment
            x = 1
            def g():
                nonlocal x
        """
    )
    texts = {o.source_name: (o.start_offset, o.end_offset) for o in occurrences_named(bindings, "alpha")}
    source = bindings.workspace.files["main.py"].text
    for role in (Role.GLOBAL_DECLARATION, Role.NONLOCAL_DECLARATION):
        for found in [o for o in bindings.occurrences if o.role is role]:
            assert source[found.start_offset : found.end_offset] == found.source_name
    assert texts


def test_every_occurrence_span_holds_its_source_name():
    bindings = analyze_source(
        """
        import a.b.c, d as e
        from f import (g as h,
            i)
        class K(Base, metaclass=Meta):
            def m(self, p=1, *args, q, **kw) -> "str": ...
        async def af[T: int, *Ts, **P](x): ...
        try:
            pass
        except* OSError as oserror:
            pass
        match v:
            case K(x=1) | {"a": w, **rest}:
                pass
        """
    )
    source = bindings.workspace.files["main.py"].text
    assert bindings.occurrences
    for found in bindings.occurrences:
        assert source[found.start_offset : found.end_offset] == found.source_name
