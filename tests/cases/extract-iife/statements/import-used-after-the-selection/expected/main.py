def root(n):
    def _extracted1(n):
        import math

        r = math.isqrt(n)
        return math, r
    math, r = _extracted1(n)
    return r + math.isqrt(1)


assert root(16) == 5
