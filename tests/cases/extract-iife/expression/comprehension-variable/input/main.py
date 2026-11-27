def scaled(values, factor):
    return [value * factor for value in values]  # [value * factor]


assert scaled([1, 2], 3) == [3, 6]
