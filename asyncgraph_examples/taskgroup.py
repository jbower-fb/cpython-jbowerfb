import asyncio

def print_graph():
  print(asyncio.async_graph_to_dot(asyncio.get_async_graph()))

async def coro_print_graph():
  print_graph()

async def use_task_group():
  async with asyncio.TaskGroup() as tg:
    tg.create_task(coro_print_graph())

async def run():
  await use_task_group()

asyncio.run(run())
