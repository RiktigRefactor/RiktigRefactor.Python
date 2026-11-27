y = 1


def f():
    x = 2
    return x


def g():
    return y


assert f() == 2
assert g() == 1
