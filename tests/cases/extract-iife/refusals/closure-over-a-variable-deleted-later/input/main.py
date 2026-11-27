def make():
    k = 1
    g = lambda: k  # [lambda: k]
    del k
    return g


try:
    make()()
except NameError:
    pass
else:
    raise AssertionError("k is deleted, so reading it must fail")
