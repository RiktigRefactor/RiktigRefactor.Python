class Base:
    pass


class Child(Base, Exception):
    n = 2
    m = n * 3  # [n * 3]


assert Child.m == 6
