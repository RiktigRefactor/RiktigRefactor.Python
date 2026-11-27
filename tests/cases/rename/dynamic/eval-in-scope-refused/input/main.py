def f():
    x = 2  # |x
    return eval("x + 1")


assert f() == 3
