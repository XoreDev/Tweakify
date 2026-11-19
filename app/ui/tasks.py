"""Background work for the UI: every slow controller call runs on the Qt thread pool.

Each request is tagged with a per-domain sequence number so a stale result (for
example an older runtime scan finishing after a newer one) is dropped.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class WorkerSignals(QObject):
    finished = Signal(str, int, object)
    failed = Signal(str, int, str)


class BackgroundTask(QRunnable):
    def __init__(self, domain: str, sequence: int, fn) -> None:
        super().__init__()
        self.domain = domain
        self.sequence = sequence
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # pragma: no cover - exercised only on runtime failures
            self._emit(self.signals.failed, str(exc))
            return
        self._emit(self.signals.finished, result)

    def _emit(self, signal, payload) -> None:
        try:
            signal.emit(self.domain, self.sequence, payload)
        except RuntimeError:
            # The window (and its signal object) was torn down while this ran; nobody is listening.
            pass


class RefreshCoordinator(QObject):
    result_ready = Signal(str, object)
    error = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.pool = QThreadPool.globalInstance()
        self._sequences: dict[str, int] = {}
        self._tasks: dict[int, BackgroundTask] = {}

    def wait_for_idle(self, timeout_ms: int = 15000) -> bool:
        """Block until queued work finishes, so closing the window never cuts an Apply in half."""
        return self.pool.waitForDone(timeout_ms)

    def is_busy(self, domain: str) -> bool:
        return any(task.domain == domain for task in self._tasks.values())

    def request(self, domain: str, fn) -> None:
        sequence = self._sequences.get(domain, 0) + 1
        self._sequences[domain] = sequence
        task = BackgroundTask(domain, sequence, fn)
        task.setAutoDelete(False)
        task.signals.finished.connect(self._handle_finished)
        task.signals.failed.connect(self._handle_failed)
        self._tasks[id(task)] = task
        task.signals.finished.connect(lambda *_args, key=id(task): self._tasks.pop(key, None))
        task.signals.failed.connect(lambda *_args, key=id(task): self._tasks.pop(key, None))
        self.pool.start(task)

    def _handle_finished(self, domain: str, sequence: int, result: object) -> None:
        if self._sequences.get(domain) != sequence:
            return
        self.result_ready.emit(domain, result)

    def _handle_failed(self, domain: str, sequence: int, message: str) -> None:
        if self._sequences.get(domain) != sequence:
            return
        self.error.emit(domain, message)
