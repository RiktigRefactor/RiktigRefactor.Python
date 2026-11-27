class Box[Elem]:
    def __init__(self, item: Elem) -> None:
        self.item = item

    def get(self) -> Elem:
        return self.item


assert Box(3).get() == 3
