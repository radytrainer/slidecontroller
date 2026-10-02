"""
Run slow work (opening PowerPoint, closing it, checking the environment) off
the GUI thread, and deliver the result back on the GUI thread.
"""

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _TaskSignals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = _TaskSignals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # delivered to the GUI as an error dialog / status
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(result)


_running: set[_Task] = set()  # keep tasks (and their signals) alive until finished


def run_task(fn: Callable[[], Any],
             on_done: Callable[[Any], None] | None = None,
             on_failed: Callable[[Exception], None] | None = None) -> None:
    """Run ``fn()`` in the thread pool; call on_done(result) / on_failed(exc) on the GUI thread."""
    task = _Task(fn)
    task.setAutoDelete(False)
    _running.add(task)

    def finish(callback, value):
        _running.discard(task)
        if callback:
            callback(value)

    task.signals.done.connect(lambda result: finish(on_done, result))
    task.signals.failed.connect(lambda exc: finish(on_failed, exc))
    QThreadPool.globalInstance().start(task)


class EngineBridge(QObject):
    """Forwards GestureEngine callbacks (engine thread) to the GUI thread."""

    ready = Signal()
    update = Signal(object)    # EngineUpdate
    command = Signal(object)   # CommandResult
    error = Signal(str)
