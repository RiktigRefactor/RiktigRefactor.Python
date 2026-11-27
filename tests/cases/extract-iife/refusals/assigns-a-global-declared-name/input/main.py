counter = 0


def bump():
    global counter
    # [
    counter += 1
    # ]


bump()
bump()
assert counter == 2
