def outer():
    count = 0
    other = 10

    def inner():
        nonlocal count  # |count
        count += 1

    inner()
    inner()
    return count, other


def sibling():
    count = 1
    total = 2
    return count, total


assert outer() == (2, 10)
assert sibling() == (1, 2)
