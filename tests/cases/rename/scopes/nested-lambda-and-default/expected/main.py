def f(y):
    g = lambda a=y: a + y
    return g()


def h():
    x = 1
    y = 2
    return x, y


assert f(4) == 8
assert h() == (1, 2)
