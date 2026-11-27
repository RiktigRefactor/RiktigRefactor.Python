def first_even(items):
    # [
    for item in items:
        if item % 2 == 0:
            return item
    # ]
    return None


assert first_even([1, 2, 3]) == 2
