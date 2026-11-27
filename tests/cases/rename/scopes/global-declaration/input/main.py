counter = 0  # |counter


def bump():
    global counter
    counter += 1


def other():
    counter = 5
    ticks = 6
    return counter, ticks


bump()
bump()
assert counter == 2
assert other() == (5, 6)
