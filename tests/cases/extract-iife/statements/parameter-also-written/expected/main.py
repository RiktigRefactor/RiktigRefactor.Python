def grow(items, extra):
    def _extracted1(items, extra):
        items = items + [extra]
        extra += 1
        return items, extra
    items, extra = _extracted1(items, extra)
    return items, extra


assert grow([1], 2) == ([1, 2], 3)
