def parse(text):
    number = 0
    try:
        def _extracted1(text):
            number = int(text)
            return number
        number = _extracted1(text)
    except ValueError:
        pass
    return number


assert parse("12") == 12
assert parse("x") == 0
