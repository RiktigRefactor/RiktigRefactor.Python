def sign(n):
    def _extracted1(n):
        if n < 0:
            label = "neg"
        else:
            label = "non-neg"
        return label
    label = _extracted1(n)
    return label


assert sign(-1) == "neg" and sign(1) == "non-neg"
