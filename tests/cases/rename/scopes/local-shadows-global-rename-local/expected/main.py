x = 1


def f():
    y = 2
    return y


def g():
    return x


assert f() == 2
assert g() == 1
