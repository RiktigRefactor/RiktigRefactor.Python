def total(items):
    result = 0  # |result
    for item in items:
        result += item
    return result


assert total([1, 2, 3]) == 6
