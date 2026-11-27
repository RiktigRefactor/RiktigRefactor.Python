zz = 12
a = f" qq = { zz !r}"
b = f"qq={zz!s}"
c = f"qq={zz:>4}"
d = f"[qq + 1={zz + 1!r}] {{braces}} (qq)={(zz)!r}"
assert a == " qq = 12", a
assert b == "qq=12", b
assert c == "qq=  12", c
assert d == "[qq + 1=13] {braces} (qq)=12", d
