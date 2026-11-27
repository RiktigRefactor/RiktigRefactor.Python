import functools


def build(n):
    def _extracted1(n):
        @functools.lru_cache(maxsize=None)
        def square(v):
            return v * v

        result = square(n)
        return result
    result = _extracted1(n)
    return result


assert build(3) == 9
