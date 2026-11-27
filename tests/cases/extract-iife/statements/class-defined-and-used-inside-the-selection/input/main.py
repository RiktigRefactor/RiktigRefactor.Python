def build(n):
    # [
    class Box:
        size = n

    result = Box.size
    # ]
    return result


assert build(4) == 4
