def f():
    x = 1  # |x
    def g():
        y = 2
        return x + y
    return g()


assert f() == 3
