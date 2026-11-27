import sys

x = 1  # |x
setattr(sys.modules[__name__], "x", 5)
assert x == 5
