def make():
    try:
        raise ValueError("a")
    except ValueError as e:
        g = lambda: e  # [lambda: e]
    return g


try:
    make()()
except NameError:
    pass
else:
    raise AssertionError("the except clause unbinds e, so reading it must fail")
