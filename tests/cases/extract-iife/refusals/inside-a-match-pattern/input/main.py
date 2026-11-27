class Color:
    RED = 1


def name(color):
    match color:
        case Color.RED:  # [Color.RED]
            return "red"
        case _:
            return "other"


assert name(1) == "red"
