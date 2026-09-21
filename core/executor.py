"""有界线程池执行器：高并发时任务排队，队列满则拒绝，避免打爆下游"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore


class ExecutorBusy(Exception):
    """任务队列已满"""


class BoundedExecutor:
    def __init__(self, max_workers: int = 16, max_queue: int = 2000):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="agent",
        )
        self._sem = BoundedSemaphore(max_workers + max_queue)

    def submit(self, fn, *args, **kwargs):
        if not self._sem.acquire(blocking=False):
            raise ExecutorBusy("任务队列已满，请稍后再试")
        try:
            future = self._executor.submit(fn, *args, **kwargs)
        except Exception:
            self._sem.release()
            raise
        future.add_done_callback(lambda _f: self._sem.release())
        return future

    def shutdown(self, wait: bool = False):
        self._executor.shutdown(wait=wait)


agent_executor = BoundedExecutor(max_workers=8, max_queue=200)
