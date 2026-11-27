class Counter:
    def __init__(self):
        self.values = []

    def add_two(self, a):
        def _extracted1(self, a):
            self.values.append(a)
            self.values.append(a + 1)
        _extracted1(self, a)
        return len(self.values)


assert Counter().add_two(1) == 2
