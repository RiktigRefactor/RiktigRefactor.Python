from lib import combined
import lib


def go():
    return combined() + lib.combined()


assert go() == 2
