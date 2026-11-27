def scale(value, *, scale_by):  # |scale_by
    return value * scale_by


assert scale(3, scale_by=2) == 6
