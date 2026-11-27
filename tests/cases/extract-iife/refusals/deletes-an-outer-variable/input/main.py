def run():
    x = 1
    # [
    del x
    # ]
    try:
        x
    except UnboundLocalError:
        return "deleted"
    return "kept"


assert run() == "deleted"
