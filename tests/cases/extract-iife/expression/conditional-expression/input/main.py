def label(n):
    return "big" if n > 10 else "small"  # ["big" if n > 10 else "small"]


assert label(11) == "big" and label(1) == "small"
