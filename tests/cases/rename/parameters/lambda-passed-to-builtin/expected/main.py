x = 1
item = 2
words = sorted(["bb", "a"], key=lambda item: len(item))
assert words == ["a", "bb"]
assert x == 1
assert item == 2
