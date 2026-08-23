from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar


T = TypeVar("T")


async def run_in_thread(
    callable_: Callable[..., T],
    *args: object,
    cancelled_result_cleanup: Callable[[T], object] | None = None,
    **kwargs: object,
) -> T:
    """Run sync work without letting repeated cancellation orphan its thread."""

    task = asyncio.create_task(asyncio.to_thread(callable_, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        result: T | None = None
        completed = False
        while not task.done():
            try:
                result = await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
            else:
                completed = True
                break
        if task.done() and not completed:
            try:
                result = task.result()
            except BaseException:
                pass
            else:
                completed = True
        if completed and cancelled_result_cleanup is not None:
            try:
                cancelled_result_cleanup(result)  # type: ignore[arg-type]
            except BaseException:
                pass
        raise
