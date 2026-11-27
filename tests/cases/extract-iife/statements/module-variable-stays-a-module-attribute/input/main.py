import sys

# [
x = 5
y = x + 1
# ]
module = sys.modules[__name__]
assert module.x == 5 and module.y == 6
