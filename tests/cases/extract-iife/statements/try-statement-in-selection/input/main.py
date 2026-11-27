def parse(text):
    # [
    try:
        value = int(text)
    except ValueError:
        value = -1
    # ]
    return value


assert parse("4") == 4 and parse("x") == -1
