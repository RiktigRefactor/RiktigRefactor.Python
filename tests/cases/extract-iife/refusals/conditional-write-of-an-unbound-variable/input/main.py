def run(flag):
    # [
    if flag:
        result = 1
    # ]
    return result if flag else 0


assert run(True) == 1 and run(False) == 0
