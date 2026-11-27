def _extracted1():
    return 1


def run(a):
    def _extracted2(a):
        b = a + _extracted1()
        return b
    b = _extracted2(a)
    return b


assert run(1) == 2
