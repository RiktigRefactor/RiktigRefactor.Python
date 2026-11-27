def f():
    x = 2  # |x
    return x + 1


def g():
    return eval("1 + 1")


assert f() == 3
assert g() == 2
