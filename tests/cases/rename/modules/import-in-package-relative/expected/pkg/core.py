from .util import y
from . import util


def run():
    assert util.y() == 2
    return y()
