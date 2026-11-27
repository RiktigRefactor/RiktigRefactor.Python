def report(values):
    def _extracted1(values):
        total = sum(values)
        count = len(values)
        return total, count
    total, count = _extracted1(values)
    mean = total / count
    def _extracted2(values):
        spread = max(values) - min(values)
        return spread
    spread = _extracted2(values)
    return mean, spread


assert report([1, 2, 3]) == (2.0, 2)
