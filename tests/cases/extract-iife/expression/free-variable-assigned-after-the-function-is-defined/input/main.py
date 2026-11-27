def outer():
    def inner():
        return k + 1  # [k + 1]

    k = 1
    return inner()


assert outer() == 2
