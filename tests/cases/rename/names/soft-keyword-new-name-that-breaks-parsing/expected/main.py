def f(case):
    match case:
        case 1:
            return 1
        case _:
            return 0


assert f(1) == 1
