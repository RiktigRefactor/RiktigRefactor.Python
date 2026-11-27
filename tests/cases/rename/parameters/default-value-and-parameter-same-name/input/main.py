size = 3


def f(size=size):  # |size#2
    return size


assert f() == 3
assert f(size=4) == 4
