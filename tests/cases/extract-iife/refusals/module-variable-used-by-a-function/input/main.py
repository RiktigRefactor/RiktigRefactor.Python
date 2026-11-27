total = 0


def add(n):
    global total
    total += n


# [
add(5)
total += 1
# ]
assert total == 6
