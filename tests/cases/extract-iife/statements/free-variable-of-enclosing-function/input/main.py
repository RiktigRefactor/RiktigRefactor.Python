def outer(offset):
    def inner(n):
        # [
        shifted = n + offset
        doubled = shifted * 2
        # ]
        return doubled

    return inner


assert outer(1)(2) == 6
