def apply(values):
    def _extracted1(values):
        def double(v):
            return v * 2

        doubled = [double(v) for v in values]
        return doubled
    doubled = _extracted1(values)
    return doubled


assert apply([1, 2]) == [2, 4]
