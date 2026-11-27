class Point:  # |Point
    def __init__(self, x):
        self.x = x


p = Point(3)
assert isinstance(p, Point)
assert type(p) is Point
