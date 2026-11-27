def report(values):
    total = sum(values)
    count = len(values)
    mean = total / count
    spread = max(values) - min(values)
    return mean, spread


assert report([1, 2, 3]) == (2.0, 2)
