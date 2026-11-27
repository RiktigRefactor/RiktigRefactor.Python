import contextlib


def run():
    seen = 0
    with contextlib.suppress(ValueError):
        # [
        seen = 1
        raise ValueError
        # ]
    return seen


assert run() == 1
