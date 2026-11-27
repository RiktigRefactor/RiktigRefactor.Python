n = 3


def f(size=n):
    return size


assert f() == 3
assert f(size=4) == 4
