def run():
    count = 0

    def inc():
        nonlocal count
        count += 1
        return count

    total = inc() + count  # [inc() + count]
    return total


assert run() == 2
