class Widget:
    exec("hidden = 3")
    size = hidden * 2  # [hidden * 2]


assert Widget.size == 6
