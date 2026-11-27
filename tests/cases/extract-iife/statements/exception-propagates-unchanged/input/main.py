def check(n):
    # [
    total = 0
    if n < 0:
        raise ValueError("negative")
    total = n
    # ]
    return total


assert check(2) == 2
try:
    check(-1)
except ValueError:
    pass
else:
    raise AssertionError("expected ValueError")
