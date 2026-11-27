def run(n):
    def _extracted1():
        from helpers import double
        return double
    double = _extracted1()
    return double(n)


assert run(4) == 8
