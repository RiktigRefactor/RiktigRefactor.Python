def count_locals(a, b):
    c = a + b
    return len(locals())  # [len(locals())]


assert count_locals(1, 2) == 3
