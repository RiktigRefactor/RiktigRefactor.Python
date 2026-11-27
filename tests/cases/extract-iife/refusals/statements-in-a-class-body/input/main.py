class Config:
    # [
    first = 1
    second = first + 1
    # ]


assert Config.second == 2
assert not hasattr(Config, "_extracted1")
