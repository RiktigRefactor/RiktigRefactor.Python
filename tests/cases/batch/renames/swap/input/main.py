def describe(width, height):
    area = width * height
    return f"{width}x{height}={area}"


assert describe(2, 3) == "2x3=6"
