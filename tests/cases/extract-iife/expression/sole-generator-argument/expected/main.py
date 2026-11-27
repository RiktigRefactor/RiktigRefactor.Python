def doubled_total(items):
    return sum((lambda items: (item * 2 for item in items))(items))


assert doubled_total([1, 2, 3]) == 12
