x = 5  # |x


class A:
    x = 1
    values = [x for _ in range(2)]


assert A.values == [5, 5]
assert getattr(A, "x") == 1
