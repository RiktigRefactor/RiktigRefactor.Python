def make(offset):
    class A:
        def get(self):
            return offset  # |offset
    return A().get()


assert make(3) == 3
