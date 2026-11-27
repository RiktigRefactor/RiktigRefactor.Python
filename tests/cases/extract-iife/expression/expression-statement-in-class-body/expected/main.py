registry = []


class Plugin:
    name = "p"
    (lambda name: registry.append(name))(name)


assert registry == ["p"]
