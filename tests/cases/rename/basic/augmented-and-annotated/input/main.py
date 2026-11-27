def run():
    count: int = 1  # |count
    count += 2
    other: int
    other = count
    return count, other


assert run() == (3, 3)
