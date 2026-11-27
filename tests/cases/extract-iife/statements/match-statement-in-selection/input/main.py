def describe(shape):
    # [
    match shape:
        case (x, y):
            label = "point"
        case _:
            label = "other"
    # ]
    return label


assert describe((1, 2)) == "point" and describe(5) == "other"
