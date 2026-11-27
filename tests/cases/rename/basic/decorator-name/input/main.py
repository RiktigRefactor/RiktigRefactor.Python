def deco(f):  # |deco
    def wrapped(*args):
        return f(*args) + 1
    return wrapped


@deco
def one():
    return 1


assert one() == 2
