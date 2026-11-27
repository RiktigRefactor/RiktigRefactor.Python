def root(n):
    # [
    import math

    r = math.isqrt(n)
    # ]
    return r + math.isqrt(1)


assert root(16) == 5
