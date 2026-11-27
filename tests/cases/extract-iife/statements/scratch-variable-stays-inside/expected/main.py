def run(items):
    def _extracted1(items):
        scratch = [item * 2 for item in items]
        total = sum(scratch)
        return total
    total = _extracted1(items)
    return total


assert run([1, 2]) == 6
