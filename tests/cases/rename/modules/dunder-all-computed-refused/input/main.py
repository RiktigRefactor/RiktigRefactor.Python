import lib

for name in lib.__all__:
    assert hasattr(lib, name)
