def f():
    y = 2
    return y + 1


def g():
    return eval("1 + 1")


assert f() == 3
assert g() == 2
