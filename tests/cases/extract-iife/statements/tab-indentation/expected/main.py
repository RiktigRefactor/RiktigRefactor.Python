def compute(a):
	x = a + 1
	def _extracted1(x):
		if x > 1:
			y = x * 2
		else:
			y = 0
		return y
	y = _extracted1(x)
	return y


assert compute(2) == 6
