def f(v):
    match v:
        case [head, *tail]:
            return head, tail
        case {"k": c, **rest}:  # |rest
            return c, rest
    return None


assert f([1, 2, 3]) == (1, [2, 3])
assert f({"k": 1, "z": 2}) == (1, {"z": 2})
