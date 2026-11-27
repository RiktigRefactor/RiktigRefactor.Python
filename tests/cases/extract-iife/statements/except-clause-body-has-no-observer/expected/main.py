def classify(text):
    status = "ok"
    try:
        int(text)
    except ValueError:
        def _extracted1():
            status = "bad"
            assert status
            return status
        status = _extracted1()
    return status


assert classify("1") == "ok"
assert classify("x") == "bad"
