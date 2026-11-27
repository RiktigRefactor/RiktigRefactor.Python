def banner(name):
    def _extracted1(name):
        text = """Hello,
  {}
end""".format(name)
        upper = text.upper()
        return text, upper
    text, upper = _extracted1(name)
    return text, upper


assert banner("x") == ("Hello,\n  x\nend", "HELLO,\n  X\nEND")
