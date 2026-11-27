class A:
    def get(this):
        return this.value

    value = 3


assert A().get() == 3
