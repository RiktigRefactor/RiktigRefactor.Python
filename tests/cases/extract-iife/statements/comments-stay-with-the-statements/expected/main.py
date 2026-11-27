def compute(a):
    def _extracted1(a):
        b = a * a  # the square
        # then add one
        c = b + 1
        return c
    c = _extracted1(a)
    return c


assert compute(3) == 10
