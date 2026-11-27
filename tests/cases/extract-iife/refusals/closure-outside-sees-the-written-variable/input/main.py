def run():
    value = 1

    def peek():
        return value

    # [
    value = 2
    seen = peek()
    # ]
    return seen


assert run() == 2
