def f():
    try:
        raise ValueError("boom")
    except ValueError as issue:
        return str(issue)


def g():
    problem = 1
    issue = 2
    return problem, issue


assert f() == "boom"
assert g() == (1, 2)
