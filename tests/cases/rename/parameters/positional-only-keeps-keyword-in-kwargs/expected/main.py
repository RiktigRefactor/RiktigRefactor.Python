def f(n, /, **kw):
    return n, kw


assert f(1, a=5) == (1, {"a": 5})
