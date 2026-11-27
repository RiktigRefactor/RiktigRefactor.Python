def tidy(n):
    def _extracted1(n):
        temp = n * 2
        result = temp + 1
        del temp
        return result
    result = _extracted1(n)
    return result


assert tidy(2) == 5
