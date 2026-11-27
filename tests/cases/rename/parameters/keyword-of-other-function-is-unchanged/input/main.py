def f(x):  # |x
    return x


def g(x, y):
    return x - y


assert f(x=5) == 5
assert g(x=5, y=2) == 3
