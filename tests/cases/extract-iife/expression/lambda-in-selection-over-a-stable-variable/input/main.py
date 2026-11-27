def adder(base):
    add = lambda n: n + base  # [lambda n: n + base]
    return add


assert adder(5)(1) == 6
