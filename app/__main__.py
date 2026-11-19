from __future__ import annotations

import argparse
import ctypes
import json
import shutil
import sys
import textwrap
from pathlib import Path
from typing import Callable, Sequence, TextIO

from PySide6.QtCore import QObject, QRectF, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

from app.controller import TweakifyController
from app.platform.elevation import ElevationDeclined, ElevationManager
from app.platform.adapters import WindowsPlatformFacade
from app.ui.main_window import TweakifyMainWindow
from app.ui.theme import BRAND_GLYPH, ICON_FONTS, palette_for


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


SPLASH_SIZE = (440, 208)
SPLASH_MARGIN = 12  # transparent border so the card's rounded corners stay crisp


def _windows_theme_mode() -> str:
    """Read the Windows app theme before any Tweakify state exists."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if int(value) == 1 else "dark"
    except (ImportError, OSError, ValueError):
        return "dark"


class LoadingSplash(QSplashScreen):
    """Startup card in the app's design system: brand mark, status line, and an indeterminate bar."""

    def __init__(self, pixmap: QPixmap, title: str, theme_mode: str = "dark") -> None:
        super().__init__(pixmap)
        self.title = title
        self.detail = LOADING_DETAIL_FRAMES[-1]
        self.frame = 0
        self.palette_tokens = palette_for(theme_mode)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def set_detail(self, detail: str) -> None:
        self.detail = detail
        self.frame += 1
        self.repaint()
        QApplication.processEvents()

    def drawContents(self, painter: QPainter) -> None:  # pragma: no cover - Qt paint path
        p = self.palette_tokens
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        card = QRectF(self.rect()).adjusted(SPLASH_MARGIN, SPLASH_MARGIN, -SPLASH_MARGIN, -SPLASH_MARGIN)
        left = card.left() + 28

        # Brand mark: accent tile with the bolt glyph.
        mark = QRectF(left, card.top() + 30, 44, 44)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(p.accent))
        painter.drawRoundedRect(mark, 10, 10)
        icon_font = QFont(ICON_FONTS[0])
        icon_font.setFamilies(list(ICON_FONTS))
        icon_font.setPixelSize(22)
        painter.setFont(icon_font)
        painter.setPen(QColor(p.accent_text))
        painter.drawText(mark, Qt.AlignCenter, BRAND_GLYPH)

        # Name and tagline.
        text_left = mark.right() + 16
        title_font = QFont("Segoe UI Variable Display")
        title_font.setFamilies(["Segoe UI Variable Display", "Segoe UI"])
        title_font.setPixelSize(24)
        title_font.setWeight(QFont.Bold)
        painter.setFont(title_font)
        painter.setPen(QColor(p.text))
        painter.drawText(QRectF(text_left, mark.top() - 4, card.width(), 30), Qt.AlignLeft | Qt.AlignVCenter, "Tweakify")
        caption_font = QFont("Segoe UI Variable Text")
        caption_font.setFamilies(["Segoe UI Variable Text", "Segoe UI"])
        caption_font.setPixelSize(13)
        painter.setFont(caption_font)
        painter.setPen(QColor(p.text_muted))
        painter.drawText(QRectF(text_left, mark.top() + 24, card.width(), 22), Qt.AlignLeft | Qt.AlignVCenter, "Performance Toolkit")

        # Status line.
        painter.setPen(QColor(p.text_muted))
        painter.drawText(
            QRectF(left, card.bottom() - 66, card.width() - 56, 20),
            Qt.AlignLeft | Qt.AlignVCenter,
            self.detail,
        )

        # Indeterminate progress bar: an accent segment sweeping across a track.
        track = QRectF(left, card.bottom() - 36, card.width() - 56, 4)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(p.border))
        painter.drawRoundedRect(track, 2, 2)
        segment = track.width() * 0.28
        travel = track.width() + segment
        offset = (self.frame * 0.07 % 1.0) * travel - segment
        clip = QPainterPath()
        clip.addRoundedRect(track, 2, 2)
        painter.save()
        painter.setClipPath(clip)
        painter.setBrush(QColor(p.accent))
        painter.drawRoundedRect(QRectF(track.left() + offset, track.top(), segment, track.height()), 2, 2)
        painter.restore()


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
    return not (args.apply_plan or args.rollback_snapshot or args.run_actions)


def _relaunch_as_admin(argv_list: Sequence[str]) -> int | None:
    """Relaunch through UAC. Returns None when elevation was declined."""
    manager = ElevationManager(_data_root(_root()) / "plans")
    command = [sys.executable, str(_launcher_path()), *argv_list]
    try:
        manager.launch_elevated(command)
    except ElevationDeclined as exc:
        # Before, a dismissed UAC prompt made the app exit with no window and no
        # message. Continue un-elevated instead; user-scope tweaks still work.
        print(str(exc), file=sys.stderr)
        return None
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tweakify: staged Windows tuning with rollback")
    parser.add_argument("--apply-plan", type=Path, help="Apply a plan JSON exported from Tweakify, then exit.")
    parser.add_argument("--rollback-snapshot", type=str, help="Roll back a recorded snapshot by id, then exit.")
    parser.add_argument(
        "--run-actions",
        type=str,
        help="Comma-separated action ids to apply (maintenance runs once), then exit. Used by scheduled maintenance.",
    )
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
    suppressed_flags = {"-h", "--help", "--apply-plan", "--rollback-snapshot", "--run-actions"}
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


def _report_transaction(transaction) -> int:
    for result in transaction.results:
        print(("OK   " if result.success else "FAIL ") + result.message)
    for note in getattr(transaction, "notes", []):
        print("NOTE " + note)
    return 1 if transaction.failed_results else 0


def _apply_cli_request(controller: TweakifyController, args: argparse.Namespace) -> int | None:
    if args.apply_plan:
        try:
            payload = json.loads(args.apply_plan.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"Could not read plan {args.apply_plan}: {exc}", file=sys.stderr)
            return 2
        controller.stage_plan_payload(payload)
        return _report_transaction(controller.apply_staged())

    if args.rollback_snapshot:
        if controller.store.load_snapshot(args.rollback_snapshot) is None:
            print(f"Snapshot {args.rollback_snapshot} was not found.", file=sys.stderr)
            return 2
        return _report_transaction(controller.rollback_snapshot(args.rollback_snapshot))

    if args.run_actions:
        unknown = controller.stage_action_ids([item.strip() for item in args.run_actions.split(",") if item.strip()])
        for action_id in unknown:
            print(f"Unknown action id: {action_id}", file=sys.stderr)
        return _report_transaction(controller.apply_staged())

    return None


def _saved_appearance() -> tuple[str, str | None]:
    """Theme and accent from settings.json, read without creating any state."""
    theme_mode, accent = _windows_theme_mode(), None
    try:
        payload = json.loads((_data_root() / "settings.json").read_text(encoding="utf-8"))
        if payload.get("theme_mode") in {"light", "dark"}:
            theme_mode = payload["theme_mode"]
        accent = payload.get("accent_color")
    except (OSError, ValueError, AttributeError):
        pass
    return theme_mode, accent


def _create_loading_splash(_app: QApplication, message: str = LOADING_MESSAGE) -> QSplashScreen:
    theme_mode, accent = _saved_appearance()
    tokens = palette_for(theme_mode, accent)
    pixmap = QPixmap(*SPLASH_SIZE)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    card = QRectF(pixmap.rect()).adjusted(SPLASH_MARGIN, SPLASH_MARGIN, -SPLASH_MARGIN, -SPLASH_MARGIN)
    # Soft drop shadow, then the card itself.
    for spread, alpha in ((8, 18), (5, 28), (2, 40)):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, alpha))
        painter.drawRoundedRect(card.adjusted(-spread, -spread + 3, spread, spread + 3), 14 + spread, 14 + spread)
    painter.setBrush(QColor(tokens.surface))
    painter.setPen(QPen(QColor(tokens.border), 1))
    painter.drawRoundedRect(card, 14, 14)
    painter.end()
    splash = LoadingSplash(pixmap, message, theme_mode)
    splash.palette_tokens = tokens
    return splash


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

    headless = bool(args.apply_plan or args.rollback_snapshot or args.run_actions)
    controller = _controller(startup_profile="full") if headless else None
    cli_result = _apply_cli_request(controller, args) if controller is not None else None
    if cli_result is not None:
        return cli_result

    if _should_relaunch_as_admin(args) and not _is_running_as_admin():
        relaunched = _relaunch_as_admin(argv_list)
        if relaunched is not None:
            return relaunched

    return _run_interactive_session(lambda: _controller(startup_profile="light"), launch_mode)


if __name__ == "__main__":
    raise SystemExit(main())


