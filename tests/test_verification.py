import pytest

from riktigrefactor.protocol import Position, RefusalError, TextEdit
from riktigrefactor.semantics import OccurrenceRole, analyze_workspace
from riktigrefactor.verification import verify_edits
from riktigrefactor.workspace import Workspace


def edit_of(workspace: Workspace, path: str, old: str, new: str, nth: int = 0) -> TextEdit:
    text = workspace.file(path).text
    index = -1
    for _ in range(nth + 1):
        index = text.index(old, index + 1)
    return workspace.edit(path, index, index + len(old), new)


def global_symbol(workspace: Workspace, path: str, name: str):
    bindings = analyze_workspace(workspace)
    return next(o.symbol for o in bindings.occurrences_in_file(path) if o.source_name == name and o.symbol.is_module_global)


def test_correct_rename_across_files_passes():
    workspace = Workspace.from_texts(
        "/w",
        {
            "lib.py": "def helper(): ...\n",
            "main.py": "from lib import helper\nimport lib\nhelper()\nlib.helper()\n",
        },
    )
    edits = [
        edit_of(workspace, "lib.py", "helper", "assist"),
        edit_of(workspace, "main.py", "helper", "assist", 0),
        edit_of(workspace, "main.py", "helper", "assist", 1),
        edit_of(workspace, "main.py", "helper", "assist", 2),
    ]
    symbol = global_symbol(workspace, "lib.py", "helper")
    local_alias = global_symbol(workspace, "main.py", "helper")
    result = verify_edits(workspace, edits, renamed_symbols={symbol: "assist", local_alias: "assist"})
    assert "assist" in result.file("lib.py").text


def test_rename_that_changes_a_binding_is_detected():
    workspace = Workspace.from_texts("/w", {"main.py": "def f(total):\n    count = 1\n    return total + count\n"})
    edits = [
        edit_of(workspace, "main.py", "total", "count", 0),
        edit_of(workspace, "main.py", "total", "count", 1),
    ]
    parameter = next(
        o.symbol for o in analyze_workspace(workspace).occurrences if o.role is OccurrenceRole.PARAMETER
    )
    with pytest.raises(RefusalError) as refusal:
        verify_edits(workspace, edits, renamed_symbols={parameter: "count"})
    assert refusal.value.code == "internal-verification-failed"


def test_rename_that_forgets_a_reference_is_detected():
    workspace = Workspace.from_texts("/w", {"main.py": "x = 1\nprint(x)\n"})
    symbol = global_symbol(workspace, "main.py", "x")
    with pytest.raises(RefusalError) as refusal:
        verify_edits(workspace, [edit_of(workspace, "main.py", "x", "y")], renamed_symbols={symbol: "y"})
    assert refusal.value.code == "internal-verification-failed"


def test_edit_that_breaks_syntax_is_detected():
    workspace = Workspace.from_texts("/w", {"main.py": "x = 1\n"})
    with pytest.raises(RefusalError) as refusal:
        verify_edits(workspace, [edit_of(workspace, "main.py", "x", "x =")])
    assert refusal.value.code == "internal-verification-failed"


def test_edit_that_does_not_compile_is_detected():
    workspace = Workspace.from_texts("/w", {"main.py": "def f():\n    x = 1\n"})
    with pytest.raises(RefusalError):
        verify_edits(workspace, [edit_of(workspace, "main.py", "x = 1", "return 1\n    nonlocal q")])


def test_unrelated_edit_shifting_offsets_keeps_scopes_comparable():
    workspace = Workspace.from_texts("/w", {"main.py": "# header\ndef f(a):\n    return [a for _ in range(2)]\n"})
    insertion = workspace.edit("main.py", 0, 0, "# a much longer header comment line\n")
    verify_edits(workspace, [insertion])


def test_edit_that_swaps_two_names_is_detected_without_renames():
    workspace = Workspace.from_texts("/w", {"main.py": "a = 1\nb = 2\nprint(a)\n"})
    with pytest.raises(RefusalError):
        verify_edits(workspace, [edit_of(workspace, "main.py", "a", "b", 1)])


def test_rewritten_regions_are_not_compared_when_the_caller_says_so():
    workspace = Workspace.from_texts("/w", {"main.py": "def f(a):\n    return a + 1\n"})
    edit = edit_of(workspace, "main.py", "a + 1", "(lambda a: a + 1)(a)")
    verify_edits(workspace, [edit], edited_regions_are_rewritten=True)
    with pytest.raises(RefusalError):
        verify_edits(workspace, [edit])
