def build(n):
    def _extracted1(n):
        class Box:
            size = n

        result = Box.size
        return result
    result = _extracted1(n)
    return result


assert build(4) == 4
