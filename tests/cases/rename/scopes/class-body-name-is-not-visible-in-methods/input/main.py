x = "global"  # |x


class A:
    x = "class"

    def get(self):
        return x


assert A().get() == "global"
assert getattr(A, "x") == "class"
