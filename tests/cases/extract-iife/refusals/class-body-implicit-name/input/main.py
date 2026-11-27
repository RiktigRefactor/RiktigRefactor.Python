class Box:
    label = __qualname__ + "!"  # [__qualname__ + "!"]


assert Box.label == "Box!"
