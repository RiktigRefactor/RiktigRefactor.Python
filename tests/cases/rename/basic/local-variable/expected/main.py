def total(items):
    acc = 0
    for item in items:
        acc += item
    return acc


assert total([1, 2, 3]) == 6
