def compute(a):
	x = a + 1
	# [
	if x > 1:
		y = x * 2
	else:
		y = 0
	# ]
	return y


assert compute(2) == 6
