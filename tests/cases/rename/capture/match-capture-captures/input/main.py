def f(v):
    x = 1  # |x
    match v:
        case [y]:
            return x + y
    return x


assert f([2]) == 3
