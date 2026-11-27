import functools


def build(n):
    # [
    @functools.lru_cache(maxsize=None)
    def square(v):
        return v * v

    result = square(n)
    # ]
    return result


assert build(3) == 9
