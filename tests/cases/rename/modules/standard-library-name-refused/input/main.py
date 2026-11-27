from os.path import join  # |join

assert join("a", "b") in ("a/b", "a\\b")
