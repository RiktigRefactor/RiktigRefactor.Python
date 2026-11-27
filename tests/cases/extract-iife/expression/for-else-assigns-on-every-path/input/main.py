def find(items, wanted):
    for item in items:
        if item == wanted:
            found = True
            break
    else:
        found = False
    message = str(found)  # [str(found)]
    return message


assert find([1, 2], 2) == "True"
assert find([1, 2], 3) == "False"
