def count_until(items, stop):
    total = 0
    for item in items:
        # [
        if item == stop:
            break
        total += item
        # ]
    return total


assert count_until([1, 2, 3], 3) == 3
