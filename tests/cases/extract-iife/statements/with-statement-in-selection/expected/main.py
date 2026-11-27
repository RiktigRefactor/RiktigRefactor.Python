import contextlib


def run(lines, log):
    def _extracted1(lines, log):
        with contextlib.nullcontext(lines) as source:
            log.append(len(source))
    _extracted1(lines, log)
    return log


assert run([1, 2], []) == [2]
