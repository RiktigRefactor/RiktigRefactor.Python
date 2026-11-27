class Quiet:
    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return True


def run(flag):
    # [
    with Quiet():
        if flag:
            raise ValueError
        count = 1
    # ]
    return 0 if flag else count


assert run(True) == 0 and run(False) == 1
