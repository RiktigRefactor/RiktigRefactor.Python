def apply(x):  # |x
    return x


fn = apply
assert fn(1) == 1
assert list(map(apply, [1, 2])) == [1, 2]
