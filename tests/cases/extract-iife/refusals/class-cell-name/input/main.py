class Thing:
    def own_class(self):
        return __class__  # [__class__]


assert Thing().own_class() is Thing
