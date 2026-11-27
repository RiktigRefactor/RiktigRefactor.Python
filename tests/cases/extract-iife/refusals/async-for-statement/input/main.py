import asyncio


async def gen():
    yield 1
    yield 2


async def total():
    result = 0
    # [
    async for item in gen():
        result += item
    # ]
    return result


assert asyncio.run(total()) == 3
