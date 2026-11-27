def banner(name):
    # [
    text = """Hello,
  {}
end""".format(name)
    upper = text.upper()
    # ]
    return text, upper


assert banner("x") == ("Hello,\n  x\nend", "HELLO,\n  X\nEND")
