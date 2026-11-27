class A:
    def m(self, x):  # |x
        return x


class B:
    def m(self, x):
        return x


assert B().m(x=1) == 1
assert A().m(1) == 1
