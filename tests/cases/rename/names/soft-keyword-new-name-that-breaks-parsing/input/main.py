def f(x):  # |x
    match x:
        case 1:
            return 1
        case _:
            return 0


assert f(1) == 1
