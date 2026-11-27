import pytest

from riktigrefactor.protocol import Position, RefusalError, TextEdit
from riktigrefactor.workspace import Workspace, module_name_for_path


def make_workspace(tmp_path, files: dict[str, str | bytes]) -> Workspace:
    for relative, content in files.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return Workspace.load(tmp_path)


def test_load_finds_python_files_and_skips_environments_and_hidden_directories(tmp_path):
    workspace = make_workspace(
        tmp_path,
        {
            "app.py": "x = 1\n",
            "pkg/__init__.py": "",
            "pkg/mod.py": "y = 2\n",
            ".git/hook.py": "bad syntax here(",
            ".hidden/thing.py": "bad syntax here(",
            "venv/pyvenv.cfg": "home = x",
            "venv/lib/site.py": "bad syntax here(",
            "pkg/__pycache__/mod.cpython-313.pyc.py": "bad syntax here(",
            "notes.txt": "not python",
        },
    )
    assert sorted(workspace.files) == ["app.py", "pkg/__init__.py", "pkg/mod.py"]


def test_module_names_support_packages_and_src_layout():
    assert module_name_for_path("app.py") == ("app", False)
    assert module_name_for_path("pkg/__init__.py") == ("pkg", True)
    assert module_name_for_path("pkg/sub/mod.py") == ("pkg.sub.mod", False)
    assert module_name_for_path("src/pkg/mod.py") == ("pkg.mod", False)
    assert module_name_for_path("src/pkg/__init__.py") == ("pkg", True)
    assert module_name_for_path("my-dir/mod.py") == (None, False)
    assert module_name_for_path("__init__.py") == (None, True)


def test_file_that_does_not_parse_is_refused_with_its_location(tmp_path):
    with pytest.raises(RefusalError) as refusal:
        make_workspace(tmp_path, {"bad.py": "x = (\n"})
    assert refusal.value.code == "file-not-parseable"
    assert refusal.value.location.file == "bad.py"


def test_unsupported_encoding_is_refused(tmp_path):
    with pytest.raises(RefusalError) as refusal:
        make_workspace(tmp_path, {"latin.py": b"# -*- coding: latin-1 -*-\nx = '\xe9'\n"})
    assert refusal.value.code == "unsupported-encoding"


def test_missing_workspace_and_missing_file(tmp_path):
    with pytest.raises(RefusalError) as refusal:
        Workspace.load(tmp_path / "nowhere")
    assert refusal.value.code == "file-not-found"
    workspace = make_workspace(tmp_path, {"a.py": ""})
    with pytest.raises(RefusalError) as refusal:
        workspace.file("b.py")
    assert refusal.value.code == "file-not-found"


def test_positions_count_unicode_scalar_values_not_utf16_units_or_bytes():
    workspace = Workspace.from_texts("/w", {"a.py": 'é = "😀" + x\nz = 1\n'})
    file = workspace.file("a.py")
    x_offset = file.text.index("x")
    assert x_offset == 10
    assert file.position_of_offset(x_offset) == Position(1, 11)
    assert file.offset_of_position(Position(1, 11)) == x_offset
    assert file.position_of_offset(file.text.index("z")) == Position(2, 1)


def test_ast_columns_are_utf8_bytes_and_are_converted_to_offsets():
    workspace = Workspace.from_texts("/w", {"a.py": 'é = "😀" + x\n'})
    file = workspace.file("a.py")
    name_x = file.tree.body[0].value.right
    assert name_x.col_offset == 14
    assert file.start_offset(name_x) == file.text.index("x")
    assert file.end_offset(name_x) == file.text.index("x") + 1


@pytest.mark.parametrize("line_break", ["\n", "\r\n", "\r"])
def test_line_breaks_of_every_kind_are_handled(line_break):
    text = f"a = 1{line_break}b = 'é'{line_break}c = b{line_break}"
    workspace = Workspace.from_texts("/w", {"a.py": text})
    file = workspace.file("a.py")
    name_c = file.tree.body[2].value
    assert file.start_offset(name_c) == text.rindex("b")
    assert file.position_of_offset(text.rindex("b")) == Position(3, 5)
    assert file.offset_of_position(Position(2, 6)) == text.index("é")


def test_form_feed_and_vertical_tab_do_not_end_lines():
    text = "a = 1\x0c\nb = 2\n"
    file = Workspace.from_texts("/w", {"a.py": text}).file("a.py")
    assert file.position_of_offset(text.index("b")) == Position(2, 1)


def test_position_past_the_end_of_a_line_or_file_is_an_invalid_selection():
    file = Workspace.from_texts("/w", {"a.py": "ab\ncd\n"}).file("a.py")
    assert file.offset_of_position(Position(1, 3)) == 2
    for position in [Position(1, 4), Position(4, 1), Position(0, 1), Position(1, 0)]:
        with pytest.raises(RefusalError) as refusal:
            file.offset_of_position(position)
        assert refusal.value.code == "invalid-selection"


def test_apply_edits_replaces_text_and_keeps_everything_else_exactly():
    workspace = Workspace.from_texts("/w", {"a.py": "x = 1  # keep\r\ny = x\r\n", "b.py": "z = 0\n"})
    edits = [
        TextEdit("a.py", Position(2, 1), Position(2, 2), "why"),
        TextEdit("a.py", Position(1, 1), Position(1, 2), "ex"),
    ]
    assert workspace.apply_edits(edits) == {"a.py": "ex = 1  # keep\r\nwhy = x\r\n"}


def test_overlapping_edits_are_rejected():
    workspace = Workspace.from_texts("/w", {"a.py": "abcdef\n"})
    edits = [TextEdit("a.py", Position(1, 1), Position(1, 4), "X"), TextEdit("a.py", Position(1, 3), Position(1, 5), "Y")]
    with pytest.raises(RefusalError) as refusal:
        workspace.apply_edits(edits)
    assert refusal.value.code == "internal-verification-failed"


def test_adjacent_edits_and_insertions_are_allowed():
    workspace = Workspace.from_texts("/w", {"a.py": "abcdef\n"})
    edits = [
        TextEdit("a.py", Position(1, 1), Position(1, 3), "X"),
        TextEdit("a.py", Position(1, 3), Position(1, 3), "-"),
        TextEdit("a.py", Position(1, 3), Position(1, 5), "Y"),
    ]
    assert workspace.apply_edits(edits) == {"a.py": "X-Yef\n"}


def test_write_texts_keeps_byte_order_marks_and_line_endings(tmp_path):
    workspace = make_workspace(tmp_path, {"a.py": b"\xef\xbb\xbfx = 1\r\n"})
    assert workspace.file("a.py").text == "x = 1\r\n"
    workspace.write_texts({"a.py": "y = 1\r\n"})
    assert (tmp_path / "a.py").read_bytes() == b"\xef\xbb\xbfy = 1\r\n"


def test_with_texts_reparses_only_the_given_files():
    workspace = Workspace.from_texts("/w", {"a.py": "x = 1\n", "b.py": "y = 1\n"})
    changed = workspace.with_texts({"a.py": "x = 2\n"})
    assert changed.file("b.py") is workspace.file("b.py")
    assert changed.file("a.py").text == "x = 2\n"
    assert workspace.file("a.py").text == "x = 1\n"
