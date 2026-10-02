"""
A single dedicated thread for COM automation.

COM objects (like PowerPoint's) belong to the thread that created them. The
gesture engine runs on a camera thread and the GUI on the main thread, so all
PowerPoint calls are funnelled through ONE worker thread with COM initialised.
``call()`` runs a function there and returns its result (or re-raises).
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import pythoncom


class ComThread:
    def __init__(self, name: str = "com"):
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=name, initializer=pythoncom.CoInitialize
        )
        self._closed = False

    def call(self, fn: Callable[..., Any], *args, timeout: float | None = 60.0, **kwargs) -> Any:
        if self._closed:
            raise RuntimeError("COM thread has been shut down")
        return self._executor.submit(fn, *args, **kwargs).result(timeout=timeout)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._executor.submit(pythoncom.CoUninitialize).result(timeout=10)
        self._executor.shutdown(wait=True)
        self._closed = True
