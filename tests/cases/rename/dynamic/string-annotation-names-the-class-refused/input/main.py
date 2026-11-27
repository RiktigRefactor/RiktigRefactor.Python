import typing


class Widget:  # |Widget
    pass


def make() -> "Widget":
    return Widget()


assert typing.get_type_hints(make)["return"] is Widget
