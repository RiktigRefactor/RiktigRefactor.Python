def _extracted1():
    return 1


def run(a):
    # [
    b = a + _extracted1()
    # ]
    return b


assert run(1) == 2
