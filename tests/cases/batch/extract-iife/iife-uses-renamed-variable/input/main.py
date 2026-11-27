def shipping_cost(weight, rate):
    cost = weight * rate
    return cost + 5


assert shipping_cost(2, 3) == 11
