def tidy(n):
    # [
    temp = n * 2
    result = temp + 1
    del temp
    # ]
    return result


assert tidy(2) == 5
