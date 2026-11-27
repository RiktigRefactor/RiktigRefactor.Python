def area(a, b, c):
    return ((lambda a, b: a + b)(a, b)) * c


assert area(1, 2, 3) == 9
