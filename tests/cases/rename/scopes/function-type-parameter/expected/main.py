T = "t"
Item = "item"


def first[Item](xs: list[Item]) -> Item:
    return xs[0]


assert first([1, 2]) == 1
assert T == "t"
assert Item == "item"
