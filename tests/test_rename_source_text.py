"""Rename and the source text that programs can observe: template strings (Python 3.14+)."""

import sys

import pytest

from riktigrefactor.protocol import Position, RefusalError, RenameRequest
from riktigrefactor.rename import rename
from riktigrefactor.workspace import Workspace


def _rename(tmp_path, text: str, position: Position, new_name: str):
    (tmp_path / "main.py").write_text(text, encoding="utf-8")
    return rename(RenameRequest("main.py", position, new_name), Workspace.load(tmp_path))


@pytest.mark.skipif(sys.version_info < (3, 14), reason="template strings need Python 3.14")
def test_name_in_a_template_string_interpolation_is_refused(tmp_path):
    result = _rename(tmp_path, 'qq = 1\ntemplate = t"{qq}"\nassert template.interpolations[0].expression == "qq"\n', Position(1, 1), "zz")
    assert [reason.code for reason in result.reasons] == ["string-names-symbol"]


@pytest.mark.skipif(sys.version_info < (3, 14), reason="template strings need Python 3.14")
def test_name_outside_the_template_string_is_renamed(tmp_path):
    result = _rename(tmp_path, 'qq = 1\nother = 2\ntemplate = t"{other}"\n', Position(1, 1), "zz")
    assert not hasattr(result, "reasons")
