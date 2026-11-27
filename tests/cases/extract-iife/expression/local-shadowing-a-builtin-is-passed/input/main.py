def first_by_key(words):
    len = lambda word: -ord(word[0])
    return max(words, key=len)  # [max(words, key=len)]


assert first_by_key(["b", "a", "c"]) == "a"
