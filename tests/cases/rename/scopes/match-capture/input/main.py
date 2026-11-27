def f(v):
    match v:
        case [left, right]:  # |left
            return left + right
        case {"k": c, **rest}:
            return c, rest
        case _:
            return None


def g():
    left = 1
    first = 2
    return left, first


assert f([1, 2]) == 3
assert f({"k": 1, "z": 2}) == (1, {"z": 2})
assert g() == (1, 2)
