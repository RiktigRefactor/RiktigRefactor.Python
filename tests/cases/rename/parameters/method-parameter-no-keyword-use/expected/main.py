class Counter:
    def __init__(self):
        self.value = 0

    def add(self, k):
        self.value += k

    def other(self, amount, k):
        return amount, k


c = Counter()
c.add(2)
assert c.value == 2
assert c.other(1, 2) == (1, 2)
