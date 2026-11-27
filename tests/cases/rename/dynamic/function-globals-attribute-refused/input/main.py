x = 2  # |x


def f():
    pass


assert f.__globals__["x"] == 2
