import pytest

from riktigrefactor.markers import MarkerError, Selection, strip_markers
from riktigrefactor.protocol import Position


def test_text_without_markers_is_unchanged():
    assert strip_markers("x = 1  # an ordinary comment\n") == ("x = 1  # an ordinary comment\n", None)


def test_quoted_selection_marks_the_quoted_text_and_removes_the_comment():
    text, selection = strip_markers("total = price * qty + shipping  # [price * qty]\n")
    assert text == "total = price * qty + shipping\n"
    assert selection == Selection(Position(1, 9), Position(1, 20))


def test_quoted_selection_with_occurrence_number():
    text, selection = strip_markers("total = x + x  # [x]#2\n")
    assert text == "total = x + x\n"
    assert selection == Selection(Position(1, 13), Position(1, 14))


def test_cursor_is_the_start_of_the_quoted_name():
    text, selection = strip_markers("a = 1\nprint(count)  # |count\n")
    assert text == "a = 1\nprint(count)\n"
    assert selection == Selection(Position(2, 7), Position(2, 7))


def test_cursor_with_occurrence_number():
    text, selection = strip_markers("f(a, a)  # |a#2\n")
    assert selection.start == Position(1, 6)


def test_multi_line_selection_covers_whole_lines_and_removes_marker_lines():
    source = "def f():\n    # [\n    a = 1\n    b = a\n    # ]\n    return b\n"
    text, selection = strip_markers(source)
    assert text == "def f():\n    a = 1\n    b = a\n    return b\n"
    assert selection == Selection(Position(2, 1), Position(3, 10))


def test_columns_count_scalar_values_in_non_ascii_text():
    text, selection = strip_markers('s = "😀é" + name  # [name]\n')
    assert selection.start == Position(1, 12)
    assert selection.end == Position(1, 16)


def test_marker_like_text_inside_strings_is_not_a_marker():
    text = 's = "# [x]"\n'
    assert strip_markers(text) == (text, None)


def test_crlf_line_endings_are_preserved():
    text, selection = strip_markers("a = 1  # [1]\r\nb = 2\r\n")
    assert text == "a = 1\r\nb = 2\r\n"
    assert selection == Selection(Position(1, 5), Position(1, 6))


def test_missing_quoted_text_is_an_error():
    with pytest.raises(MarkerError):
        strip_markers("a = 1  # [zzz]\n")
    with pytest.raises(MarkerError):
        strip_markers("a = 1  # [1]#2\n")


def test_two_selections_are_an_error():
    with pytest.raises(MarkerError):
        strip_markers("a = 1  # [1]\nb = 2  # [2]\n")


def test_unpaired_range_markers_are_errors():
    with pytest.raises(MarkerError):
        strip_markers("# [\na = 1\n")
    with pytest.raises(MarkerError):
        strip_markers("a = 1\n# ]\n")


def test_cursor_matches_whole_identifiers_before_substrings():
    text, selection = strip_markers("try:\n    pass\nexcept ValueError as e:  # |e\n    pass\n")
    assert selection == Selection(Position(3, 22), Position(3, 22))
    assert text.splitlines()[2] == "except ValueError as e:"
    text, selection = strip_markers("value = 1  # |e\n")
    assert selection == Selection(Position(1, 5), Position(1, 5))
