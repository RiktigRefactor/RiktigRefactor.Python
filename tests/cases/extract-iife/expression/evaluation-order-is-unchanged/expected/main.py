def observe(log, label):
    log.append(label)
    return label


def run():
    log = []
    both = (lambda log: observe(log, "a") + observe(log, "b"))(log)
    assert log == ["a", "b"]
    return both


assert run() == "ab"
