def f(x):  # |x
    g = lambda a=x: a + x
    return g()


def h():
    x = 1
    y = 2
    return x, y


assert f(4) == 8
assert h() == (1, 2)
