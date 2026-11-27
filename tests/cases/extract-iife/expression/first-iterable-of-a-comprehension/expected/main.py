def copy(items):
    return [v for v in (lambda items: items)(items)]


assert copy([1, 2]) == [1, 2]
