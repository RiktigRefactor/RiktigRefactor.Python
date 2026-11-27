def outer():
    def inner():
        return (lambda k: k + 1)(k)

    k = 1
    return inner()


assert outer() == 2
