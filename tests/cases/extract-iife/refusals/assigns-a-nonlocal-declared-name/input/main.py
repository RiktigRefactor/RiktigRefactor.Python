def make():
    count = 0

    def inc():
        nonlocal count
        # [
        count += 1
        # ]
        return count

    return inc


inc = make()
inc()
assert inc() == 2
