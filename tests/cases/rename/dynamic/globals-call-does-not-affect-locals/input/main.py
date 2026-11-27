def f():
    x = 2  # |x
    return x


assert globals().get("f") is f
assert f() == 2
