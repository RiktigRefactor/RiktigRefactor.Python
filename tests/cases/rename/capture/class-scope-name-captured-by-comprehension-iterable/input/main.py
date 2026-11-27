def f(xs):  # |xs
    class A:
        y = [1, 2]
        values = [v for v in xs]
    return A.values


assert f([5]) == [5]
