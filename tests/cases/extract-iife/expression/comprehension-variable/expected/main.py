def scaled(values, factor):
    return [(lambda value, factor: value * factor)(value, factor) for value in values]


assert scaled([1, 2], 3) == [3, 6]
