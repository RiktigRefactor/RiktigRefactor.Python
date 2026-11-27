def f():
    x = 2  # |x
    return locals()["x"]


assert f() == 2
