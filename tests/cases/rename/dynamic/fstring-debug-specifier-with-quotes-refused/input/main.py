names = {"a": 1}  # |names
text = f"{names['a']=}"
assert text == "names['a']=1", text
