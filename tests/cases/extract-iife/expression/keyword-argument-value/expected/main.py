def render(label, width):
    return "{:>{w}}".format(label, w=(lambda width: width + 1)(width))


assert render("x", 2) == "  x"
