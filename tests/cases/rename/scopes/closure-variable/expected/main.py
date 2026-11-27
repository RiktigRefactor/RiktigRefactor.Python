def make(base):
    def add(x):
        return x + base
    return add


assert make(3)(4) == 7
