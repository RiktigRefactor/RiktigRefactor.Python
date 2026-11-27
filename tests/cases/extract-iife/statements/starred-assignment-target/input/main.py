def split(items):
    # [
    first, *rest = items
    count = len(rest)
    # ]
    return first, rest, count


assert split([1, 2, 3]) == (1, [2, 3], 2)
