def run():
    value = 1

    def peek():
        return value

    # [
    value = 2
    # ]
    return peek()


assert run() == 2
