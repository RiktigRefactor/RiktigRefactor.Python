import config

assert config.rate == 2  # |rate
config.rate = 3
assert config.rate == 3
