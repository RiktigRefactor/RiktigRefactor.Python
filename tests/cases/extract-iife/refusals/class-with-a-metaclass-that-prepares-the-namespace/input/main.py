class Meta(type):
    @classmethod
    def __prepare__(mcls, name, bases, **kwargs):
        return {"injected": 10}


class Widget(metaclass=Meta):
    size = injected * 2  # [injected * 2]


assert Widget.size == 20
