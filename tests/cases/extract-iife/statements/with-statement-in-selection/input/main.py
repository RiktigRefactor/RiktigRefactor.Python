import contextlib


def run(lines, log):
    # [
    with contextlib.nullcontext(lines) as source:
        log.append(len(source))
    # ]
    return log


assert run([1, 2], []) == [2]
