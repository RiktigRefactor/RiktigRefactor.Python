def sign(n):
    # [
    if n < 0:
        label = "neg"
    else:
        label = "non-neg"
    # ]
    return label


assert sign(-1) == "neg" and sign(1) == "non-neg"
