import sys


def separator():
    # [
    import os.path
    # ]
    return os.path.sep


assert separator() == __import__("os").path.sep
