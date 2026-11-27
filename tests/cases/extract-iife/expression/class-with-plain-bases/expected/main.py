class Base:
    pass


class Child(Base, Exception):
    n = 2
    m = (lambda n: n * 3)(n)


assert Child.m == 6
