def f(a, /, **kw):  # |a
    return a, kw


assert f(1, a=5) == (1, {"a": 5})
