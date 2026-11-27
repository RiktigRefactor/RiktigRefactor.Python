class Box[T]:  # |T
    def __init__(self, item: T) -> None:
        self.item = item

    def get(self) -> T:
        return self.item


assert Box(3).get() == 3
