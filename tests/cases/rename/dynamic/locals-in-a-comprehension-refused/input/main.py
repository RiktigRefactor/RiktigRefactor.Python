def f():
    x = 2  # |x
    return [locals()["x"] for _ in range(1)][0]


assert f() == 2
