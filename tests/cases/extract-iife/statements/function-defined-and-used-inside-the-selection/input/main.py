def apply(values):
    # [
    def double(v):
        return v * 2

    doubled = [double(v) for v in values]
    # ]
    return doubled


assert apply([1, 2]) == [2, 4]
