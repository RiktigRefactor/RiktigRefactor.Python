def pick(flag):
    if flag:
        x = 1
    return x + 1 if flag else 0  # [x + 1 if flag else 0]


assert pick(True) == 2 and pick(False) == 0
