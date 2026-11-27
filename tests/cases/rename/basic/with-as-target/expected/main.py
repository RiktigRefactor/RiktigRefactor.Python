import io


def run():
    with io.StringIO("abc") as handle:
        data = handle.read()
    return data


assert run() == "abc"
