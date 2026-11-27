x = 1
item = 2
words = sorted(["bb", "a"], key=lambda x: len(x))  # |x
assert words == ["a", "bb"]
assert x == 1
assert item == 2
