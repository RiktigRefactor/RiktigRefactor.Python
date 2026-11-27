def deco(f):
    def wrapper(*args, **kwargs):
        return f(*args, **kwargs)
    return wrapper


@deco
def f(x):  # |x
    return x


assert f(x=1) == 1
