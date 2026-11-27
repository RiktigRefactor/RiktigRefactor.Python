import asyncio


async def compute(a):
    value = await asyncio.sleep(0, a + 1)  # [await asyncio.sleep(0, a + 1)]
    return value


assert asyncio.run(compute(1)) == 2
