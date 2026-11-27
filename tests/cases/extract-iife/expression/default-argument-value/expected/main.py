SCALE = 3


def scale(n, factor=(lambda: SCALE * 2)()):
    return n * factor


assert scale(2) == 12
