def step(a, b):
    # [
    a += 1
    b = a * 2
    # ]
    return a, b


assert step(1, 0) == (2, 4)
