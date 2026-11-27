def last_index(count):
    index = -1
    def _extracted1(index, count):
        for index in range(count):
            pass
        return index
    index = _extracted1(index, count)
    return index


assert last_index(3) == 2 and last_index(0) == -1
