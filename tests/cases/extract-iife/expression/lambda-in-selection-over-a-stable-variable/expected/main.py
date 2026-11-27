def adder(base):
    add = (lambda base: lambda n: n + base)(base)
    return add


assert adder(5)(1) == 6
