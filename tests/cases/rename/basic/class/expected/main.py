class Vertex:
    def __init__(self, x):
        self.x = x


p = Vertex(3)
assert isinstance(p, Vertex)
assert type(p) is Vertex
