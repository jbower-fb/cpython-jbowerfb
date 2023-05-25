from __future__ import annotations

"""Tools for extracting and visualizing the logical call graph of a Python
program, including dependencies between Tasks, Futures, etc."""

__all__ = (
    '_current_task', 'AsyncGraphAwaitable', 'AsyncGraphNode',
    'AsyncGraphNodeAsyncGraphAwaitable', 'AsyncGraphNodeFrame',
    'AsyncGraphNodeError', 'get_async_graph', 'async_graph_to_dot',
)

import inspect
import sys
import types

from abc import ABC, abstractmethod
from typing import Self, Set

from . import events

# Assigned in tasks.py
_current_task = None


class AsyncGraphAwaitable(ABC):
    """Classes of this type can participate in the construction of a logical
    call graph including asynchronous operations."""

    def __init__(self) -> None:
        self._awaiters = set()

    def get_awaiters(self) -> Set[Self]:
        """Return the set of AsyncGraphAwaitables currently waiting for this
        awaitable to complete."""
        return self._awaiters

    def add_awaiter(self, awaiter: Self) -> None:
        """Add a dependent awaiter on this awaitable."""
        self._awaiters.add(awaiter)

    @abstractmethod
    def makeAsyncGraphNodes(self) -> (AsyncGraphNode, AsyncGraphNode):
        """Construct AsyncGraphNodes forming a sub-graph representing this
        awaitable.

        Returns the tail and head nodes of the resulting sub-graph."""


class AsyncGraphNode(ABC):
    """Base type for nodes in a logical call graph."""

    def __init__(self) -> None:
        self.awaited_by: Set[AsyncGraphNode] = set()

    def get_awaiters(self) -> Set[AsyncGraphAwaitable]:
        return set()

    @abstractmethod
    def __str__(self) -> str:
        ...


class AsyncGraphNodeAsyncGraphAwaitable(AsyncGraphNode):
    def __init__(self, awaitable: AsyncGraphAwaitable) -> None:
        super().__init__()
        self.awaitable = awaitable

    def get_awaiters(self):
        return self.awaitable.get_awaiters()

    def __str__(self) -> str:
        return str(self.awaitable)


class AsyncGraphNodeFrame(AsyncGraphNode):
    def __init__(self, frame: types.FrameType) -> None:
        super().__init__()
        self.frame = frame

    def __str__(self) -> str:
        return str(self.frame)


class AsyncGraphNodeError(AsyncGraphNode):
    def __init__(self, text: str, awaiters=set()) -> None:
        super().__init__()
        self.text = text
        self._awaiters = awaiters

    def get_awaiters(self):
        return self._awaiters

    def __str__(self) -> str:
        return self.text


def get_async_graph() -> AsyncGraphNode:
    """
    Generate a logical call graph from the top of the stack to the entry point
    of the Python program. The graph includes call/await dependencies between
    regular functions, coroutines, Futures, and other participating awaitables.
    The result is the node at the top of the logical call graph (i.e. the
    caller of this function).

    For example for the following code:
        def get_graph():
            ... get_async_await_graph() ...

       async def coro_get_graph():
            await get_graph()

        def main():
            asyncio.run(b())

    We would get a graph in get_graph() which looks approximately like this:

        [frame for get_graph()] ->
        [frame for coro_get_graph()] ->
        [Task for coro_get_graph] ->
         ... [frames through the innards of asyncio.run()] ... ->
        [frame for main()]

    Note the output only shows a portion of the graph from caller to entry-
    point. It does not include other pending Futures etc.
    """

    frame = sys._getframe(1)

    # If there is no current task, assume we aren't running an event loop and
    # just walk the stack in a conventional fashion.
    loop = events.get_running_loop()
    if loop is None or _current_task(loop) is None:
        head_node = AsyncGraphNodeFrame(frame)
        tail_node = head_node
        while frame.f_back is not None:
            frame = frame.f_back
            new_node = AsyncGraphNodeFrame(frame)
            tail_node.awaited_by.add(new_node)
            tail_node = new_node

        return head_node


    # Traverse the graph of dependent AsyncGraphAwaitables. Tasks will unroll
    # to a series of "frame" nodes for their local call stacks.
    cur_task = _current_task(loop)
    task_node, task_head_node = cur_task.makeAsyncGraphNodes()
    head_node = task_head_node
    tail_node = task_node

    node_q = [task_node]
    terminal_async_nodes = set()
    awaitable_to_head_node = {cur_task: task_head_node}

    while node_q:
        node = node_q.pop()
        awaiters = node.get_awaiters()
        if len(awaiters) == 0:
            terminal_async_nodes.add(node)
        for child_awaitable in awaiters:
            if child_awaitable in awaitable_to_head_node:
                node.awaited_by.add(
                        awaitable_to_head_node[child_awaitable])
            else:
                child_node, child_head_node = \
                        child_awaitable.makeAsyncGraphNodes()
                awaitable_to_head_node[child_awaitable] = child_node
                node_q.append(child_node)
                node.awaited_by.add(child_head_node)

    assert len(terminal_async_nodes) > 0

    # Now attach the top of the graph. These will be a series of zero or more
    # frames from the top of the regular call stack until the first frame
    # covered by the current task.
    if type(head_node) is AsyncGraphNodeFrame:
        cur_task_exit_frame = head_node.frame
        tail_node = head_node
        head_node = None
        while frame is not cur_task_exit_frame:
            new_node = AsyncGraphNodeFrame(frame)
            if head_node is None:
                head_node = new_node
            else:
                tail_node.awaited_by.add(new_node)
            tail_node = new_node
            frame = frame.f_back
            if frame is None:
                new_node = AsyncGraphNodeError(
                        "Could not find exit frame for current task")
                tail_node.awaited_by.add(new_node)
                tail_node = new_node
                break
        tail_node.awaited_by.add(task_head_node)

    # Finally, the bottom of the graph. This is all the frames after the current
    # task leading to the program entry-point.
    cur_task_entry_frame = cur_task.get_coro().cr_frame
    while frame:
        if frame is cur_task_entry_frame:
            frame = frame.f_back
            break
        frame = frame.f_back

    if frame is None:
        new_node = AsyncGraphNodeError(
                "Could not link current task to entry point.")
        tail_node.awaited_by.add(new_node)
    else:
        tail_node = None
        while frame is not None:
            new_node = AsyncGraphNodeFrame(frame)
            if tail_node is None:
                for terminal_async_node in terminal_async_nodes:
                    terminal_async_node.awaited_by.add(new_node)
            else:
                tail_node.awaited_by.add(new_node)
            tail_node = new_node
            frame = frame.f_back

    return head_node


def async_graph_to_dot(head: AsyncGraphNode) -> str:
    """
    Render an async call graph into a file suitable for GraphViz dot.
    """

    graph = "digraph {\n"
    seen = set()
    next_id = 0
    node_to_id = {}


    def node_id(node: AsyncGraphNode) -> int:
        nonlocal next_id
        node_id = node_to_id.get(node)
        if node_id is None:
            node_to_id[node] = node_id = next_id = next_id + 1
        return node_id


    q = [head]
    while q:
        node = q.pop()
        if node in seen:
            continue
        seen.add(node)
        label = str(node).replace("\n", '\\n').replace('"', '\"')
        graph += f"  n{node_id(node)} [label=\"{label}\" shape=box];\n"
        for child in node.awaited_by:
            q.append(child)
            graph += f"n{node_id(node)} -> n{node_id(child)};\n"
    graph += ("}\n")

    return graph
