"""
Run code on the GUI thread from any thread.

Qt windows may only be created and changed on the GUI thread, but the photo
slideshow is started from a worker thread (like PowerPoint) and navigated
from the gesture-engine thread::

    run_on_gui(create_window)              # waits for the result
    run_on_gui(lambda: show(3), wait=False)
"""

import threading
from typing import Any, Callable

from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, Signal, Slot


class _Invoker(QObject):
    call = Signal(object)

    @Slot(object)
    def run(self, fn) -> None:
        fn()


_invoker: _Invoker | None = None
_lock = threading.Lock()


def _get_invoker() -> _Invoker:
    global _invoker
    with _lock:
        if _invoker is None:
            app = QCoreApplication.instance()
            if app is None:
                raise RuntimeError("No QApplication")
            invoker = _Invoker()
            invoker.moveToThread(app.thread())
            invoker.call.connect(invoker.run, Qt.QueuedConnection)
            _invoker = invoker
        return _invoker


def on_gui_thread() -> bool:
    app = QCoreApplication.instance()
    return app is not None and QThread.currentThread() is app.thread()


def run_on_gui(fn: Callable[[], Any], wait: bool = True, timeout: float = 15.0) -> Any:
    if on_gui_thread():
        return fn()
    invoker = _get_invoker()
    if not wait:
        invoker.call.emit(fn)
        return None
    done = threading.Event()
    result: dict[str, Any] = {}

    def call() -> None:
        try:
            result["value"] = fn()
        except BaseException as exc:  # handed back to the calling thread
            result["error"] = exc
        finally:
            done.set()

    invoker.call.emit(call)
    if not done.wait(timeout):
        raise TimeoutError("The GUI thread did not respond")
    if "error" in result:
        raise result["error"]
    return result.get("value")
