def apply(y):
    return y


fn = apply
assert fn(1) == 1
assert list(map(apply, [1, 2])) == [1, 2]
