def scale(value, *, factor):
    return value * factor


assert scale(3, factor=2) == 6
