from textlib import combine
import textlib

assert combine(["a", "b"]) == "a-b"
assert ",".join(["a", "b"]) == "a,b"
assert textlib.combine(["c"]) == "c"
