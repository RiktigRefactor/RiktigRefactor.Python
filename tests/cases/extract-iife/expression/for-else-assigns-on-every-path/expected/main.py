def find(items, wanted):
    for item in items:
        if item == wanted:
            found = True
            break
    else:
        found = False
    message = (lambda found: str(found))(found)
    return message


assert find([1, 2], 2) == "True"
assert find([1, 2], 3) == "False"
