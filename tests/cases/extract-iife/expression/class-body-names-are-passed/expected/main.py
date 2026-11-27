class Settings:
    base = 10
    doubled = (lambda base: base * 2)(base)


assert Settings.doubled == 20
