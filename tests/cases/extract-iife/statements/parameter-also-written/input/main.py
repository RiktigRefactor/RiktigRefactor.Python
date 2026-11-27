def grow(items, extra):
    # [
    items = items + [extra]
    extra += 1
    # ]
    return items, extra


assert grow([1], 2) == ([1, 2], 3)
