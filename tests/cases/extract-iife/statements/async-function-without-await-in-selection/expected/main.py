import asyncio


async def run(a):
    def _extracted1(a):
        b = a * 2
        c = b + 1
        return c
    c = _extracted1(a)
    await asyncio.sleep(0)
    return c


assert asyncio.run(run(1)) == 3
