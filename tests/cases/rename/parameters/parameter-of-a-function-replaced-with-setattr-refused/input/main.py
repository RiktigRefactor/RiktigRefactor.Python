import lib

setattr(lib, "f", lambda aa: aa * 2)
assert lib.f(aa=3) == 6
