def doubled_total(items):
    return sum(item * 2 for item in items)  # [(item * 2 for item in items)]


assert doubled_total([1, 2, 3]) == 12
