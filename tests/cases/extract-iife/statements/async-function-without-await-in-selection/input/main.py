import asyncio


async def run(a):
    # [
    b = a * 2
    c = b + 1
    # ]
    await asyncio.sleep(0)
    return c


assert asyncio.run(run(1)) == 3
