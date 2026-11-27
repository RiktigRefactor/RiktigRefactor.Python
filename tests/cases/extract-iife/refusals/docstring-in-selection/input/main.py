def documented():
    # [
    """Says hello."""
    # ]
    return "hello"


assert documented.__doc__ == "Says hello."
