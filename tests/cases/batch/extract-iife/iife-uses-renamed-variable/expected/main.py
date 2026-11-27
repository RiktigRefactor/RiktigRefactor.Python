def shipping_cost(mass, rate):
    cost = (lambda mass, rate: mass * rate)(mass, rate)
    return cost + 5


assert shipping_cost(2, 3) == 11
