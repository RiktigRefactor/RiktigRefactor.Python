size = 3


def f(n=size):
    return n


assert f() == 3
assert f(n=4) == 4
