def run(items):
    # [
    scratch = [item * 2 for item in items]
    total = sum(scratch)
    # ]
    return total


assert run([1, 2]) == 6
