x = 1  # |x


class A:
    y = x
    x = 2


assert A.y == 1
assert A.x == 2
