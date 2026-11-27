import asyncio


async def fetch_total(a, b):
    await asyncio.sleep(0)
    return (lambda a, b: a * b + 1)(a, b)


assert asyncio.run(fetch_total(2, 3)) == 7
