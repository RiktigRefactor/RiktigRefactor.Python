def describe(shape):
    def _extracted1(shape):
        match shape:
            case (x, y):
                label = "point"
            case _:
                label = "other"
        return label
    label = _extracted1(shape)
    return label


assert describe((1, 2)) == "point" and describe(5) == "other"
