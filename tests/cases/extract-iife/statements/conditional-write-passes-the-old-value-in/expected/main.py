def bump(flag):
    total = 1
    def _extracted1(flag, total):
        if flag:
            total = 5
        return total
    total = _extracted1(flag, total)
    return total


assert bump(True) == 5 and bump(False) == 1
