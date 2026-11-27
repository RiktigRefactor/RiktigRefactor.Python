def numbers(values):
    for value in values:
        yield (lambda value: value * 2)(value)


assert list(numbers([1, 2])) == [2, 4]
