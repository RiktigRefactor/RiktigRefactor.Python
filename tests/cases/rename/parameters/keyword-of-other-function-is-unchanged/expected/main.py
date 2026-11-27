def f(y):
    return y


def g(x, y):
    return x - y


assert f(y=5) == 5
assert g(x=5, y=2) == 3
