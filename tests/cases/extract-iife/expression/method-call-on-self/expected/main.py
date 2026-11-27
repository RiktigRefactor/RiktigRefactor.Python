class Bag:
    def __init__(self):
        self.items = [1, 2, 2]

    def twos(self, value):
        return (lambda self, value: self.items.count(value))(self, value)


assert Bag().twos(2) == 2
