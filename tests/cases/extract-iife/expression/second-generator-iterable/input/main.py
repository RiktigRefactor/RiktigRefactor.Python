def flatten(rows):
    return [y for x in rows for y in x]  # [x]#2


assert flatten([[1], [2, 3]]) == [1, 2, 3]
