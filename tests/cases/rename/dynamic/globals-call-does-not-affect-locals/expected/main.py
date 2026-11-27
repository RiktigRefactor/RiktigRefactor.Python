def f():
    y = 2
    return y


assert globals().get("f") is f
assert f() == 2
