def countdown(n):
    steps = 0
    # [
    while n > 0:
        n -= 1
        steps += 1
    # ]
    return steps, n


assert countdown(3) == (3, 0)
