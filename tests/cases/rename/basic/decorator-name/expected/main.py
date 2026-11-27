def wrapper_factory(f):
    def wrapped(*args):
        return f(*args) + 1
    return wrapped


@wrapper_factory
def one():
    return 1


assert one() == 2
