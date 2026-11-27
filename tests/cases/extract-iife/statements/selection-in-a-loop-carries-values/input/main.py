def run(n):
    acc = 0
    prev = 0
    for i in range(n):
        # [
        prev = acc
        acc = acc + i
        # ]
    return acc, prev


assert run(4) == (6, 3)
