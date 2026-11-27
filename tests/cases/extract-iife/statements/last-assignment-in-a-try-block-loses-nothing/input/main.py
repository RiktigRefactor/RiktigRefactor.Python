def parse(text):
    number = 0
    try:
        # [
        number = int(text)
        # ]
    except ValueError:
        pass
    return number


assert parse("12") == 12
assert parse("x") == 0
