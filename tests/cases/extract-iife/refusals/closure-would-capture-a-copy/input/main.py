def run():
    value = 1
    # [
    show = lambda: value
    # ]
    value = 2
    return show()


assert run() == 2
