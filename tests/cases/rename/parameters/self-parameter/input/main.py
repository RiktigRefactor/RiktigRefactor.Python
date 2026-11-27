class A:
    def get(self):  # |self
        return self.value

    value = 3


assert A().get() == 3
