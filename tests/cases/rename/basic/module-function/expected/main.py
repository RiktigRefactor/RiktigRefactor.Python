def grand_total(items):
    return sum(items)


assert grand_total([1, 2]) == 3
values = [grand_total, len]
assert values[0]([5]) == 5
