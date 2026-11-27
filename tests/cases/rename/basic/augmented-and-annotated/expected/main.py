def run():
    n: int = 1
    n += 2
    other: int
    other = n
    return n, other


assert run() == (3, 3)
