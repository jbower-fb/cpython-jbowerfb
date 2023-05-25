import asyncio

def print_graph():
  print(asyncio.async_graph_to_dot(asyncio.get_async_graph()))

async def coro_print_graph(f1, f2):
  await f1
  print_graph()
  f2.set_result(None)

async def other_coro(f1, f2):
  f1.set_result(None)
  await f2

async def use_task_group():
  loop = asyncio.get_running_loop()
  f1 = loop.create_future()
  f2 = loop.create_future()
  async with asyncio.TaskGroup() as tg:
    tg.create_task(coro_print_graph(f1, f2))
    await other_coro(f1, f2)

async def run():
  await use_task_group()

asyncio.run(run())
