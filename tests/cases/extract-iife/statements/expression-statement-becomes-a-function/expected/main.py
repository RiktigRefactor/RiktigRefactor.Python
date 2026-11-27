def record(log, value):
    def _extracted1(log, value):
        log.append(value)
    _extracted1(log, value)


log = []
record(log, 1)
assert log == [1]
