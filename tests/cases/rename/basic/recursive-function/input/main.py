def count_down(n):  # |count_down
    if n == 0:
        return 0
    return count_down(n - 1)


assert count_down(3) == 0
