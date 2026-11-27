def pair(a, b):
    result = (lambda a, b: (a, b))(a, b)
    return result


assert pair(1, 2) == (1, 2)
