y = 5


class A:
    x = 1
    values = [y for _ in range(2)]


assert A.values == [5, 5]
assert getattr(A, "x") == 1
