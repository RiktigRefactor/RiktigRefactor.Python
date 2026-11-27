size = 3


def f(size=size):  # |size
    return size


assert f() == 3
assert f(size=4) == 4
