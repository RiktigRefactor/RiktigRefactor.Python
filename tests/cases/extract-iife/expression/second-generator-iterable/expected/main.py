def flatten(rows):
    return [y for x in rows for y in (lambda x: x)(x)]


assert flatten([[1], [2, 3]]) == [1, 2, 3]
