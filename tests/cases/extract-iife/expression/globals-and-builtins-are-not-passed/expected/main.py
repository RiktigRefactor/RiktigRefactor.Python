OFFSET = 10


def count_with_offset(items):
    return (lambda items: len(items) + OFFSET)(items)


assert count_with_offset([1, 2, 3]) == 13
