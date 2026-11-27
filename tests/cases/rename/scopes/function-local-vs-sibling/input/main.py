def first(n):
    x = n * 2  # |x
    return x


def second(n):
    x = n + 1
    y = n + 100
    return x, y


assert first(1) == 2
assert second(1) == (2, 101)
