def run():
    value = 1

    def peek():
        return value

    def _extracted1():
        value = 2
        return value
    value = _extracted1()
    return peek()


assert run() == 2
