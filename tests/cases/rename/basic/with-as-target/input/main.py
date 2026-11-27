import io


def run():
    with io.StringIO("abc") as stream:  # |stream
        data = stream.read()
    return data


assert run() == "abc"
