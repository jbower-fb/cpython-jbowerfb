import asyncio

def print_graph():
  print(asyncio.async_graph_to_dot(asyncio.get_async_graph()))

async def coro_print_graph(f):
  await f
  print_graph()

async def coro_await(f1, f2):
  await f1
  await f2

async def release_futures(*futs):
  for f in futs:
    f.set_result(None)
    await asyncio.sleep(0)

async def run():
  loop = asyncio.get_running_loop()
  f_release_print = loop.create_future()
  c = coro_print_graph(f_release_print)
  tc = loop.create_task(c)
  f_release_awaits = loop.create_future()
  t1_tc = loop.create_task(coro_await(f_release_awaits, tc))
  t2_tc = loop.create_task(coro_await(f_release_awaits, tc))
  await asyncio.gather(t1_tc, t2_tc, release_futures(f_release_awaits, f_release_print))

asyncio.run(run())
