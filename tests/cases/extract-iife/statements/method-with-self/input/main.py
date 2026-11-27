class Counter:
    def __init__(self):
        self.values = []

    def add_two(self, a):
        # [
        self.values.append(a)
        self.values.append(a + 1)
        # ]
        return len(self.values)


assert Counter().add_two(1) == 2
