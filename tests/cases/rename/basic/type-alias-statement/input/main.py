type Pair = tuple[int, int]  # |Pair


def swap(p: Pair) -> Pair:
    return (p[1], p[0])


assert swap((1, 2)) == (2, 1)
