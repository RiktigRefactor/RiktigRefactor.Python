from textlib import join
import textlib

assert join(["a", "b"]) == "a-b"
assert ",".join(["a", "b"]) == "a,b"
assert textlib.join(["c"]) == "c"
