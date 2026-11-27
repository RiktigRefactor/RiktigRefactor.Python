class Account:
    def total(self, amount):
        __fee = 2
        return (lambda amount, __fee: amount + __fee)(amount, __fee)


assert Account().total(5) == 7
