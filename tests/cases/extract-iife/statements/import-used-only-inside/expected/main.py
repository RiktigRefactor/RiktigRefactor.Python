def root(n):
    def _extracted1(n):
        import math

        r = math.isqrt(n)
        return r
    r = _extracted1(n)
    return r


assert root(16) == 4
