from .util import helper
from . import util


def run():
    assert util.helper() == 2
    return helper()
