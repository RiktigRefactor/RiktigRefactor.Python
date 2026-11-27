qq = 12  # |qq
a = f"{ qq = }"
b = f"{qq=!s}"
c = f"{qq=:>4}"
d = f"[{qq + 1=}] {{braces}} {(qq)=}"
assert a == " qq = 12", a
assert b == "qq=12", b
assert c == "qq=  12", c
assert d == "[qq + 1=13] {braces} (qq)=12", d
