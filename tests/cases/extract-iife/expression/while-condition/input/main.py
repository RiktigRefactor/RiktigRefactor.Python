def count_up(limit):
    n = 0
    while n < limit * 2:  # [limit * 2]
        n += 1
    return n


assert count_up(2) == 4
