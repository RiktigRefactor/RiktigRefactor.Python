import sys

def _extracted1():
    x = 5
    y = x + 1
    return x, y
x, y = _extracted1()
module = sys.modules[__name__]
assert module.x == 5 and module.y == 6
