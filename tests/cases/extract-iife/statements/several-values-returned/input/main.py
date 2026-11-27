def area_and_perimeter(width, height):
    # [
    area = width * height
    perimeter = 2 * (width + height)
    # ]
    return area, perimeter


assert area_and_perimeter(2, 3) == (6, 10)
