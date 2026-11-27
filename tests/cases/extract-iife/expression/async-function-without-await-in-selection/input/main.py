import asyncio


async def fetch_total(a, b):
    await asyncio.sleep(0)
    return a * b + 1  # [a * b + 1]


assert asyncio.run(fetch_total(2, 3)) == 7
