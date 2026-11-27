from lib import helper
import lib


def go():
    return helper() + lib.helper()


assert go() == 2
