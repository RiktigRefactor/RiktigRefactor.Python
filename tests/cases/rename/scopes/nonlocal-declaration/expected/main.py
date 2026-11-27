def outer():
    total = 0
    other = 10

    def inner():
        nonlocal total
        total += 1

    inner()
    inner()
    return total, other


def sibling():
    count = 1
    total = 2
    return count, total


assert outer() == (2, 10)
assert sibling() == (1, 2)
