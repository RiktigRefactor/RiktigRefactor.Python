def f(*args, **kwargs):  # |args
    return args, kwargs


assert f(1, args=2) == ((1,), {"args": 2})
