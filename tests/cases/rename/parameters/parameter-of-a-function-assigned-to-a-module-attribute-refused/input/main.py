import lib


def mine(aa):  # |aa
    return aa * 2


lib.f = mine
assert lib.f(aa=3) == 6
