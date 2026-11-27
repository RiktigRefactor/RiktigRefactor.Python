def answer():
    return (lambda: 6 * 7)()


assert answer() == 42
