def totals(rows):
    out = []
    for row in rows:
        if row:
            # [
            first = row[0]
            rest = sum(row[1:])
            # ]
            out.append(first + rest)
    return out


assert totals([[1, 2, 3], [], [4]]) == [6, 4]
