def outer(flag):
    def inner():
        return flag and k + 1  # [flag and k + 1]

    result = inner()
    k = 1
    return result


assert outer(False) is False
