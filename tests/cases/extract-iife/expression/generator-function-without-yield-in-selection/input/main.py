def numbers(values):
    for value in values:
        yield value * 2  # [value * 2]


assert list(numbers([1, 2])) == [2, 4]
