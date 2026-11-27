def run(n):
    acc = 0
    prev = 0
    for i in range(n):
        def _extracted1(acc, i):
            prev = acc
            acc = acc + i
            return prev, acc
        prev, acc = _extracted1(acc, i)
    return acc, prev


assert run(4) == (6, 3)
