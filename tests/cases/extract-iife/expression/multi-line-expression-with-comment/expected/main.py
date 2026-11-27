def combine(first, second, third):
    return (
        (lambda first, second, third: first
        + second  # the middle one
        + third)(first, second, third)
    )


assert combine(1, 2, 3) == 6
