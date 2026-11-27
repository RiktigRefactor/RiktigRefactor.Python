def f():
    __tmp = 1  # |__tmp
    return __tmp


assert f() == 1
