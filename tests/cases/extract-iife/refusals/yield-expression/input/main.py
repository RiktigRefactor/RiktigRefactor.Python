def echo():
    received = yield 1  # [yield 1]
    yield received


gen = echo()
assert next(gen) == 1
assert gen.send("x") == "x"
