import sys


def separator():
    def _extracted1():
        import os.path
        return os
    os = _extracted1()
    return os.path.sep


assert separator() == __import__("os").path.sep
