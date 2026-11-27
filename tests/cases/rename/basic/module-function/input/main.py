def total(items):  # |total
    return sum(items)


assert total([1, 2]) == 3
values = [total, len]
assert values[0]([5]) == 5
