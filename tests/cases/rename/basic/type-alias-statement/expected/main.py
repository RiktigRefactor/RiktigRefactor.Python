type Couple = tuple[int, int]


def swap(p: Couple) -> Couple:
    return (p[1], p[0])


assert swap((1, 2)) == (2, 1)
