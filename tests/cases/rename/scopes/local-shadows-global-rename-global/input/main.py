x = 1  # |x


def f():
    x = 2
    return x


def g():
    return x


assert f() == 2
assert g() == 1
