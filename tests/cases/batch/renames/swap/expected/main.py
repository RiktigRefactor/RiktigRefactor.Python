def describe(height, width):
    area = height * width
    return f"{height}x{width}={area}"


assert describe(2, 3) == "2x3=6"
