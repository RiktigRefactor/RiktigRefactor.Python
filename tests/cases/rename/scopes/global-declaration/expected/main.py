ticks = 0


def bump():
    global ticks
    ticks += 1


def other():
    counter = 5
    ticks = 6
    return counter, ticks


bump()
bump()
assert ticks == 2
assert other() == (5, 6)
