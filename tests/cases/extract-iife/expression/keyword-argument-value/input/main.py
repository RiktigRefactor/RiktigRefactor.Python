def render(label, width):
    return "{:>{w}}".format(label, w=width + 1)  # [width + 1]


assert render("x", 2) == "  x"
