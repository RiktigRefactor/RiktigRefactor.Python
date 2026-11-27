def collect(items):
    result = []
    # [
    for item in items:
        result.append(item * 2)
    # ]
    return result


assert collect([1, 2]) == [2, 4]
