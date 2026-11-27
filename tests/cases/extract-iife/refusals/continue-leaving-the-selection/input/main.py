def sum_odd(items):
    total = 0
    for item in items:
        # [
        if item % 2 == 0:
            continue
        total += item
        # ]
    return total


assert sum_odd([1, 2, 3]) == 4
