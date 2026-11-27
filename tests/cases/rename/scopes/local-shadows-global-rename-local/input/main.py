x = 1


def f():
    x = 2  # |x
    return x


def g():
    return x


assert f() == 2
assert g() == 1
