def label(n):
    return (lambda n: "big" if n > 10 else "small")(n)


assert label(11) == "big" and label(1) == "small"
