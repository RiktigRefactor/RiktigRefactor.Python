def make(base):
    # [
    def add(n):
        return n + base

    fn = add
    # ]
    return fn


assert make(3)(4) == 7
