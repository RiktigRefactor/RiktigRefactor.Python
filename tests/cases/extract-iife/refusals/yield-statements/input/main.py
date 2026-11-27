def numbers():
    # [
    yield 1
    yield 2
    # ]
    yield 3


assert list(numbers()) == [1, 2, 3]
