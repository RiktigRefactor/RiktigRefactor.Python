def parse(text):
    def _extracted1(text):
        try:
            value = int(text)
        except ValueError:
            value = -1
        return value
    value = _extracted1(text)
    return value


assert parse("4") == 4 and parse("x") == -1
