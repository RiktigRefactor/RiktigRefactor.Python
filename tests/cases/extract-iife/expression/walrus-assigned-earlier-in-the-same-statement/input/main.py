def pair(first, second):
    return (first, second)


def run():
    return pair((y := 5), y + 1)  # [y + 1]


assert run() == (5, 6)
