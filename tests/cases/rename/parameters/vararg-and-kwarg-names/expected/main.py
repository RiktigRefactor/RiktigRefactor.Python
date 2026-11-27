def f(*rest, **kwargs):
    return rest, kwargs


assert f(1, args=2) == ((1,), {"args": 2})
