def f(xs):
    out = [y for x in xs if (y := x * 2) > 2]  # |y
    return out, y


def g():
    y = 1
    z = 2
    return y, z


assert f([1, 2, 3]) == ([4, 6], 6)
assert g() == (1, 2)
