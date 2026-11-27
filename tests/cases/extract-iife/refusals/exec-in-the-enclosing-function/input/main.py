def run():
    out = {}
    # [
    value = 7
    # ]
    exec("out['v'] = value")
    return out


assert run() == {"v": 7}
