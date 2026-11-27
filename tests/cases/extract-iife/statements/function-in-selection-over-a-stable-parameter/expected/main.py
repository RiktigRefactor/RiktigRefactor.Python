def make(base):
    def _extracted1(base):
        def add(n):
            return n + base

        fn = add
        return fn
    fn = _extracted1(base)
    return fn


assert make(3)(4) == 7
