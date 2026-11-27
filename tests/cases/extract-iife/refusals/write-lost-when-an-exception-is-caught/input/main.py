def run():
    status = "start"
    try:
        # [
        status = "working"
        raise ValueError("boom")
        # ]
    except ValueError:
        pass
    return status


assert run() == "working"
