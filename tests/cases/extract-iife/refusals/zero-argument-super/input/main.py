class Base:
    def label(self):
        return "base"


class Child(Base):
    def label(self):
        prefix = ">"
        return prefix + super().label()  # [prefix + super().label()]


assert Child().label() == ">base"
