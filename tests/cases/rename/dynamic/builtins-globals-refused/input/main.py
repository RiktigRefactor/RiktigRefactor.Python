import builtins

x = 2  # |x
assert builtins.globals()["x"] == 2
