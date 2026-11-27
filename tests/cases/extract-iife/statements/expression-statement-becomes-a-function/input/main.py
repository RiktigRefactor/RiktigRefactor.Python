def record(log, value):
    # [
    log.append(value)
    # ]


log = []
record(log, 1)
assert log == [1]
