def make_peek(step):
    count = 10

    def peek():
        return (lambda count, step: count + step)(count, step)

    return peek


assert make_peek(5)() == 15
