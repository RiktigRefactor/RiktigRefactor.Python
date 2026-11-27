def run(values):
    out = []
    for v in values:  # |v
        out.append(v * 2)
    del v
    return out


assert run([1, 2]) == [2, 4]
