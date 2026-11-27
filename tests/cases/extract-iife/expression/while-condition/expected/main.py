def count_up(limit):
    n = 0
    while n < (lambda limit: limit * 2)(limit):
        n += 1
    return n


assert count_up(2) == 4
