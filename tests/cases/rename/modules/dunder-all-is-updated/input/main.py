import lib

for name in lib.__all__:
    assert hasattr(lib, name)
assert sorted(lib.__all__) == sorted(["helper", "other"]) or sorted(lib.__all__) == sorted(["assist", "other"])
