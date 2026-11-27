def first_by_key(words):
    len = lambda word: -ord(word[0])
    return (lambda words, len: max(words, key=len))(words, len)


assert first_by_key(["b", "a", "c"]) == "a"
