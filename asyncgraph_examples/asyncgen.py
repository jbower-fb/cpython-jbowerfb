import asyncio

def print_graph():
  print(asyncio.async_graph_to_dot(asyncio.get_async_graph()))

async def coro_print_graph():
  print_graph()

async def ag():
  t = asyncio.get_running_loop().create_task(coro_print_graph())
  await t
  yield None

async def use_ag():
  async for _ in ag():
    pass

asyncio.run(use_ag())
