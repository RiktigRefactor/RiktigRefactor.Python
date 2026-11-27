def classify(value, limit):
    match value:
        case number if (lambda number, limit: number > limit)(number, limit):
            return "big"
        case _:
            return "small"


assert classify(5, 3) == "big"
assert classify(1, 3) == "small"
