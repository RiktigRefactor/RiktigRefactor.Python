def observe(log, label):
    log.append(label)
    return label


def run():
    log = []
    both = observe(log, "a") + observe(log, "b")  # [observe(log, "a") + observe(log, "b")]
    assert log == ["a", "b"]
    return both


assert run() == "ab"
