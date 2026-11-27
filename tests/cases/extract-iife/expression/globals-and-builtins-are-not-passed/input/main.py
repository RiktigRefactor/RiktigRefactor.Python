OFFSET = 10


def count_with_offset(items):
    return len(items) + OFFSET  # [len(items) + OFFSET]


assert count_with_offset([1, 2, 3]) == 13
