def run(values):
    out = []
    for item in values:
        out.append(item * 2)
    del item
    return out


assert run([1, 2]) == [2, 4]
