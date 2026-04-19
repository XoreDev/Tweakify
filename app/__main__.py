from __future__ import annotations

import argparse
import ctypes
import json
import shutil
import sys
import textwrap
from pathlib import Path
from typing import Callable, Sequence, TextIO

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

from app.controller import TweakifyController
from app.platform.elevation import ElevationManager
from app.platform.adapters import WindowsPlatformFacade
from app.ui.main_window import TweakifyMainWindow


LOADING_MESSAGE = "Loading Tweakify GUI"
LOADING_DETAIL_FRAMES = (
    "Loading Tweakify.",
    "Loading Tweakify..",
    "Loading Tweakify...",
)
LOADED_MESSAGE = "Tweakify Loaded"
LOADED_ASCII_ART = r"""
Tweakify Loaded
"""


class BootstrapWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, controller_factory: Callable[[], TweakifyController]) -> None:
        super().__init__()
        self.controller_factory = controller_factory

    def run(self) -> None:
        try:
            controller = self.controller_factory()
        except Exception as exc:  # pragma: no cover - runtime failure path
            self.failed.emit(str(exc))
            return
        self.finished.emit(controller)


class LoadingSplash(QSplashScreen):
    def __init__(self, pixmap: QPixmap, title: str) -> None:
        super().__init__(pixmap)
        self.title = title
        self.detail = LOADING_DETAIL_FRAMES[-1]
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.FramelessWindowHint, True)

    def set_detail(self, detail: str) -> None:
        self.detail = detail
        self.repaint()
        QApplication.processEvents()

    def drawContents(self, painter: QPainter) -> None:  # pragma: no cover - Qt paint path
        painter.setRenderHint(QPainter.Antialiasing)

        title_rect = self.rect().adjusted(34, 42, -34, -74)
        detail_rect = self.rect().adjusted(34, 104, -34, -28)

        painter.setPen(QColor(255, 248, 252))
        title_font = QFont("Segoe UI", 17, QFont.Bold)
        title_font.setLetterSpacing(QFont.PercentageSpacing, 103)
        painter.setFont(title_font)
        painter.drawText(title_rect, Qt.AlignHCenter | Qt.AlignVCenter, self.title)

        painter.setPen(QColor(255, 239, 247, 220))
        detail_font = QFont("Segoe UI", 9)
        painter.setFont(detail_font)
        painter.drawText(detail_rect, Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, self.detail)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _data_root(app_root: Path | None = None) -> Path:
    root = app_root or _root()
    return root / "data"


def _launcher_path(app_root: Path | None = None) -> Path:
    root = app_root or _root()
    return root / "Tweakify.py"


def _controller(startup_profile: str = "full") -> TweakifyController:
    root = _root()
    data_root = _data_root(root)
    return TweakifyController(
        platform=WindowsPlatformFacade(root, data_root=data_root),
        storage_root=data_root,
        startup_profile=startup_profile,
    )


def _is_running_as_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _should_relaunch_as_admin(args: argparse.Namespace) -> bool:
    return not (args.apply_plan or args.rollback_snapshot)


def _relaunch_as_admin(argv_list: Sequence[str]) -> int:
    manager = ElevationManager(_data_root(_root()) / "plans")
    command = [sys.executable, str(_launcher_path()), *argv_list]
    manager.launch_elevated(command)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tweakify GUI rewrite")
    parser.add_argument("--apply-plan", type=Path)
    parser.add_argument("--rollback-snapshot", type=str)
    return parser


def should_show_console_loading(
    argv: Sequence[str] | None = None,
    stdout: TextIO | None = None,
) -> bool:
    args = list(sys.argv[1:] if argv is None else argv)
    stream = stdout or sys.stdout
    is_interactive = bool(getattr(stream, "isatty", lambda: False)())
    if not is_interactive:
        return False
    suppressed_flags = {"-h", "--help", "--apply-plan", "--rollback-snapshot"}
    return not any(flag in args for flag in suppressed_flags)


def build_console_loading_banner(
    columns: int | None = None,
    rows: int | None = None,
    message: str = LOADING_MESSAGE,
) -> str:
    terminal_size = shutil.get_terminal_size(fallback=(80, 24))
    width = max(columns or terminal_size.columns, 40)
    height = max(rows or terminal_size.lines, 8)
    card_width = min(max(len(message) + 14, 36), max(36, width - 10))
    inner_width = card_width - 2
    card_lines = [
        "+" + "-" * inner_width + "+",
        "|" + " " * inner_width + "|",
        "|" + message.center(inner_width) + "|",
        "|" + " " * inner_width + "|",
        "+" + "-" * inner_width + "+",
    ]
    top_padding = max(0, (height - len(card_lines)) // 2)
    centered_lines = [line.center(width) for line in card_lines]
    return ("\n" * top_padding) + "\n".join(centered_lines) + "\n"


def _print_console_loading_banner(stdout: TextIO | None = None) -> None:
    stream = stdout or sys.stdout
    terminal_size = shutil.get_terminal_size(fallback=(80, 24))
    stream.write(
        build_console_loading_banner(
            columns=terminal_size.columns,
            rows=terminal_size.lines,
        )
    )
    stream.flush()


def build_console_loaded_banner(
    columns: int | None = None,
    rows: int | None = None,
    art: str = LOADED_ASCII_ART,
) -> str:
    terminal_size = shutil.get_terminal_size(fallback=(160, 36))
    width = max(columns or terminal_size.columns, 120)
    height = max(rows or terminal_size.lines, 18)
    art_lines = textwrap.dedent(art).strip("\n").splitlines()
    subtitle = LOADED_MESSAGE
    inner_width = max([len(line) for line in art_lines] + [len(subtitle)]) + 6
    show_subtitle = [line.strip() for line in art_lines] != [subtitle]
    card_lines = [
        "╔" + "═" * inner_width + "╗",
        "║" + " " * inner_width + "║",
        *[f"║{line.center(inner_width)}║" for line in art_lines],
        "║" + " " * inner_width + "║",
    ]
    if show_subtitle:
        card_lines.extend(
            [
                f"║{subtitle.center(inner_width)}║",
                "║" + " " * inner_width + "║",
            ]
        )
    card_lines.append("╚" + "═" * inner_width + "╝")
    top_padding = max(0, (height - len(card_lines)) // 2)
    centered_lines = [line.center(width) for line in card_lines]
    return ("\n" * top_padding) + "\n".join(centered_lines) + "\n"
def _print_console_loaded_banner(stdout: TextIO | None = None) -> None:
    stream = stdout or sys.stdout
    if not bool(getattr(stream, "isatty", lambda: False)()):
        return
    terminal_size = shutil.get_terminal_size(fallback=(160, 36))
    stream.write(
        build_console_loaded_banner(
            columns=terminal_size.columns,
            rows=terminal_size.lines,
        )
    )
    stream.flush()


def _apply_cli_request(controller: TweakifyController, args: argparse.Namespace) -> int | None:
    if args.apply_plan:
        payload = json.loads(args.apply_plan.read_text(encoding="utf-8"))
        for change in payload.get("changes", []):
            controller.stage_action(change["action_id"], change["target_state"])
        for change in payload.get("startup_changes", []):
            controller.stage_startup_entry(change["entry_id"], change["target_enabled"])
        controller.apply_staged()
        return 0

    if args.rollback_snapshot:
        controller.rollback_snapshot(args.rollback_snapshot)
        return 0

    return None


def _create_loading_splash(_app: QApplication, message: str = LOADING_MESSAGE) -> QSplashScreen:
    pixmap = QPixmap(420, 180)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    gradient = QLinearGradient(0, 0, pixmap.width(), pixmap.height())
    gradient.setColorAt(0.0, QColor(233, 95, 177, 224))
    gradient.setColorAt(1.0, QColor(121, 90, 245, 224))
    painter.setBrush(gradient)
    painter.setPen(QPen(QColor(255, 255, 255, 70), 1))
    painter.drawRoundedRect(10, 10, pixmap.width() - 20, pixmap.height() - 20, 28, 28)
    painter.end()
    return LoadingSplash(pixmap, message)


def _exec_application(app: QApplication) -> int:
    return app.exec()


class BootstrapSession(QObject):
    finished = Signal(int)

    def __init__(
        self,
        app: QApplication,
        controller_factory: Callable[[], TweakifyController],
        launch_mode: str,
    ) -> None:
        super().__init__(app)
        self.app = app
        self.controller_factory = controller_factory
        self.launch_mode = launch_mode
        self.exit_code = 0
        self.window: TweakifyMainWindow | None = None
        self.splash = _create_loading_splash(app)
        self.splash.show()
        self.app.processEvents()

        self.loading_messages = list(LOADING_DETAIL_FRAMES)
        self.loading_index = 0
        self.loading_timer = QTimer(self)
        self.loading_timer.setInterval(160)
        self.loading_timer.timeout.connect(self.update_loading_message)
        self.update_loading_message()
        self.loading_timer.start()

        self.worker_thread = QThread(self)
        self.worker = BootstrapWorker(controller_factory)
        self.worker.moveToThread(self.worker_thread)
        self.worker.finished.connect(self._handle_success, Qt.QueuedConnection)
        self.worker.failed.connect(self._handle_failure, Qt.QueuedConnection)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.failed.connect(self.worker.deleteLater)
        self.worker_thread.started.connect(self.worker.run)
        self.app.aboutToQuit.connect(self._request_thread_stop)

    def start(self) -> None:
        self.worker_thread.start()

    @Slot()
    def update_loading_message(self) -> None:
        message = self.loading_messages[self.loading_index % len(self.loading_messages)]
        self.loading_index += 1
        if isinstance(self.splash, LoadingSplash):
            self.splash.set_detail(message)
        elif hasattr(self.splash, "set_detail"):
            self.splash.set_detail(message)

    @Slot(object)
    def _handle_success(self, controller: TweakifyController) -> None:
        self.window = TweakifyMainWindow(controller)
        if not self.window.isVisible():
            self.window.show()
        self.splash.finish(self.window)
        self.loading_timer.stop()
        if self.launch_mode == "console":
            _print_console_loaded_banner()
        self._request_thread_stop()
        self.finished.emit(0)

    @Slot(str)
    def _handle_failure(self, message: str) -> None:
        self.exit_code = 1
        self.loading_timer.stop()
        self.splash.close()
        self._request_thread_stop()
        QMessageBox.critical(None, "Tweakify Startup Error", message)
        QTimer.singleShot(0, self.app.quit)
        self.finished.emit(1)

    @Slot()
    def _request_thread_stop(self) -> None:
        if self.worker_thread.isRunning():
            self.worker_thread.quit()


def _run_interactive_session(
    controller_factory: Callable[[], TweakifyController],
    launch_mode: str,
) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    session = BootstrapSession(app, controller_factory, launch_mode)
    session.start()
    app_exit_code = _exec_application(app)
    if session.worker_thread.isRunning():
        session.worker_thread.wait(5000)
    return session.exit_code if session.exit_code else app_exit_code


def main(argv: list[str] | None = None, launch_mode: str = "console") -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    args = _build_parser().parse_args(argv_list)

    controller = _controller(startup_profile="full") if (args.apply_plan or args.rollback_snapshot) else None
    cli_result = _apply_cli_request(controller, args) if controller is not None else None
    if cli_result is not None:
        return cli_result

    if _should_relaunch_as_admin(args) and not _is_running_as_admin():
        return _relaunch_as_admin(argv_list)

    return _run_interactive_session(lambda: _controller(startup_profile="light"), launch_mode)


if __name__ == "__main__":
    raise SystemExit(main())


