def bump(flag):
    total = 1
    # [
    if flag:
        total = 5
    # ]
    return total


assert bump(True) == 5 and bump(False) == 1
