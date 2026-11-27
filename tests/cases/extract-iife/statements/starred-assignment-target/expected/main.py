def split(items):
    def _extracted1(items):
        first, *rest = items
        count = len(rest)
        return first, rest, count
    first, rest, count = _extracted1(items)
    return first, rest, count


assert split([1, 2, 3]) == (1, [2, 3], 2)
