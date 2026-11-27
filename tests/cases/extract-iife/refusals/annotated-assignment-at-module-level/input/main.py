import sys

# [
x: int = 5
# ]
assert sys.modules[__name__].__annotations__ == {"x": int}
