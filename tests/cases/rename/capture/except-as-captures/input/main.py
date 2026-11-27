def f():
    value = 1  # |value
    try:
        raise ValueError("x")
    except ValueError as err:
        return value, str(err)


assert f() == (1, "x")
