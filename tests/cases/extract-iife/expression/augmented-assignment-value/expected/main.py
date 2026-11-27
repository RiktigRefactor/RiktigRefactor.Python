def add_line(total, price, qty):
    total += (lambda price, qty: price * qty)(price, qty)
    return total


assert add_line(1, 2, 3) == 7
