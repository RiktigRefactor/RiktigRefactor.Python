def countdown(n):
    steps = 0
    def _extracted1(n, steps):
        while n > 0:
            n -= 1
            steps += 1
        return n, steps
    n, steps = _extracted1(n, steps)
    return steps, n


assert countdown(3) == (3, 0)
