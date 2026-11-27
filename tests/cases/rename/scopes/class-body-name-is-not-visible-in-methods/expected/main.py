y = "global"


class A:
    x = "class"

    def get(self):
        return y


assert A().get() == "global"
assert getattr(A, "x") == "class"
