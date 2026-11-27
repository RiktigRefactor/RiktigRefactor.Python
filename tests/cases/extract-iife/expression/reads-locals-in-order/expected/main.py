def total_cost(price, qty, shipping):
    subtotal = price * qty
    return (lambda subtotal, shipping: subtotal + shipping)(subtotal, shipping)


assert total_cost(3, 4, 5) == 17
