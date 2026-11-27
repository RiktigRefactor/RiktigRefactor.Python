def make(offset):
    def add(x):
        return x + offset  # |offset
    return add


assert make(3)(4) == 7
