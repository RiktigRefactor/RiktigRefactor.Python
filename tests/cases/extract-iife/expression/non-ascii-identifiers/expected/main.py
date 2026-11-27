def doubled(größe):
    größe2 = größe + 1
    return (lambda größe2: größe2 * 2)(größe2)


assert doubled(1) == 4
