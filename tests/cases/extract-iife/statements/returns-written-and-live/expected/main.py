def step(a, b):
    def _extracted1(a):
        a += 1
        b = a * 2
        return a, b
    a, b = _extracted1(a)
    return a, b


assert step(1, 0) == (2, 4)
