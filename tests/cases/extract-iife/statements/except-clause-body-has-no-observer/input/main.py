def classify(text):
    status = "ok"
    try:
        int(text)
    except ValueError:
        # [
        status = "bad"
        assert status
        # ]
    return status


assert classify("1") == "ok"
assert classify("x") == "bad"
