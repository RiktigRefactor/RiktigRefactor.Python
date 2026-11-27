def make():
    k = 1
    item = None
    values = (k for item in range(2))  # [(k for item in range(2))]
    del k
    return values


try:
    list(make())
except NameError:
    pass
else:
    raise AssertionError("k is deleted, so reading it must fail")
