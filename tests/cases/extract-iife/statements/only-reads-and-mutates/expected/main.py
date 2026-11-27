def collect(items):
    result = []
    def _extracted1(items, result):
        for item in items:
            result.append(item * 2)
    _extracted1(items, result)
    return result


assert collect([1, 2]) == [2, 4]
