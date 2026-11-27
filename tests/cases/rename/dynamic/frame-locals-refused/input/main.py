import sys


def f():
    x = 2  # |x
    return sys._getframe().f_locals["x"]


assert f() == 2
