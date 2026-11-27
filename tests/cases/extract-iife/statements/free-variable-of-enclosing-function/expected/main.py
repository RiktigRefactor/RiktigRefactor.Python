def outer(offset):
    def inner(n):
        def _extracted1(n, offset):
            shifted = n + offset
            doubled = shifted * 2
            return doubled
        doubled = _extracted1(n, offset)
        return doubled

    return inner


assert outer(1)(2) == 6
