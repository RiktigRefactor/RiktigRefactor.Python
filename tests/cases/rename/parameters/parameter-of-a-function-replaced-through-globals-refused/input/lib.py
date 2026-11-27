def f(aa):  # |aa
    return aa


globals()["f"] = lambda aa: aa * 2
