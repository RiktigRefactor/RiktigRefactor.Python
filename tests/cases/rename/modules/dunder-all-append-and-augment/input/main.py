import lib

for name in lib.__all__:
    assert hasattr(lib, name)
assert len(lib.__all__) == 3
