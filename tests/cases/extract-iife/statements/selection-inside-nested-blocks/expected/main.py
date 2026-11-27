def totals(rows):
    out = []
    for row in rows:
        if row:
            def _extracted1(row):
                first = row[0]
                rest = sum(row[1:])
                return first, rest
            first, rest = _extracted1(row)
            out.append(first + rest)
    return out


assert totals([[1, 2, 3], [], [4]]) == [6, 4]
