def identity[T](value: T) -> T:
    doubled = [value, value]  # [[value, value]]
    return doubled[0]


assert identity(1) == 1
