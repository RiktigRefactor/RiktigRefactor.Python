def outer():
    x = 2  # |x

    def inner():
        return x + locals()["x"]

    return inner()


assert outer() == 4
