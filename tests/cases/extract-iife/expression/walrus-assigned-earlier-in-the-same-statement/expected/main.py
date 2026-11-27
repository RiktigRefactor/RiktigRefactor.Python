def pair(first, second):
    return (first, second)


def run():
    return pair((y := 5), (lambda y: y + 1)(y))


assert run() == (5, 6)
