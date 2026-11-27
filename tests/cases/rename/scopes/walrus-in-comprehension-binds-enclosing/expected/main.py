def f(xs):
    out = [z for x in xs if (z := x * 2) > 2]
    return out, z


def g():
    y = 1
    z = 2
    return y, z


assert f([1, 2, 3]) == ([4, 6], 6)
assert g() == (1, 2)
