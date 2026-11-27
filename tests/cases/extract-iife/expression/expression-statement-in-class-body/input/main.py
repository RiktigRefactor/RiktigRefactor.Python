registry = []


class Plugin:
    name = "p"
    registry.append(name)  # [registry.append(name)]


assert registry == ["p"]
