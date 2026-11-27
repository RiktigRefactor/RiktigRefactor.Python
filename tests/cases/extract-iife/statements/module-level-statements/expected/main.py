numbers = [1, 2, 3]
def _extracted1():
    total = 0
    total += sum(numbers)
    return total
total = _extracted1()
assert total == 6
