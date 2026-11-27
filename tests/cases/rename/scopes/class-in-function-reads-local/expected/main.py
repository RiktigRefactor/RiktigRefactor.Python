def make(base):
    class A:
        def get(self):
            return base
    return A().get()


assert make(3) == 3
