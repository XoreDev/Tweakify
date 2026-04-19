import io
import subprocess
import sys
from pathlib import Path

import app.__main__ as app_main
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QWidget

from tests.conftest import CONSOLE_LAUNCHER, GUI_LAUNCHER, ROOT


class _TtyBuffer(io.StringIO):
    def isatty(self) -> bool:  # pragma: no cover - trivial helper
        return True


class _PipeBuffer(io.StringIO):
    def isatty(self) -> bool:  # pragma: no cover - trivial helper
        return False


def test_console_loading_banner_contains_loading_tweakify():
    banner = app_main.build_console_loading_banner(columns=72, rows=20)

    assert "Loading Tweakify" in banner
    assert "+" in banner
    assert "|" in banner
    assert all(ord(character) < 128 for character in banner)


def test_console_loading_banner_is_suppressed_for_help_apply_rollback_and_pipes(tmp_path: Path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}", encoding="utf-8")

    assert app_main.should_show_console_loading([], stdout=_TtyBuffer()) is True
    assert app_main.should_show_console_loading(["--help"], stdout=_TtyBuffer()) is False
    assert app_main.should_show_console_loading(["--apply-plan", str(plan_path)], stdout=_TtyBuffer()) is False
    assert app_main.should_show_console_loading(["--rollback-snapshot", "snap-001"], stdout=_TtyBuffer()) is False
    assert app_main.should_show_console_loading([], stdout=_PipeBuffer()) is False


def test_console_launch_does_not_render_ascii_loading_banner(monkeypatch):
    output = _TtyBuffer()
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(app_main, "_run_interactive_session", lambda *_args, **_kwargs: 0)

    exit_code = app_main.main([], launch_mode="console")

    assert exit_code == 0
    assert output.getvalue() == ""


def test_runtime_roots_resolve_inside_app_folder():
    app_root = app_main._root()

    assert app_main._launcher_path(app_root) == app_root / "Tweakify.py"
    assert app_main._data_root(app_root) == app_root / "data"


def test_loading_message_uses_loading_tweakify_gui():
    assert app_main.LOADING_MESSAGE == "Loading Tweakify GUI"


def test_console_loaded_banner_contains_loaded_message_and_box():
    banner = app_main.build_console_loaded_banner(columns=220, rows=30)

    assert "Tweakify Loaded" in banner
    assert banner.count("Tweakify Loaded") == 1
    assert "╔" in banner
    assert "╚" in banner


def test_gui_launcher_help_executes_from_repo_root():
    result = subprocess.run(
        [sys.executable, str(GUI_LAUNCHER), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Tweakify GUI rewrite" in result.stdout


def test_console_launcher_help_executes_from_repo_root():
    result = subprocess.run(
        [sys.executable, str(CONSOLE_LAUNCHER), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Tweakify GUI rewrite" in result.stdout


def test_gui_launch_routes_through_shared_interactive_session(monkeypatch, qapp):
    captured: dict[str, object] = {}

    monkeypatch.setattr(app_main, "_is_running_as_admin", lambda: True, raising=False)
    monkeypatch.setattr(
        app_main,
        "_controller",
        lambda startup_profile="full": captured.setdefault("startup_profiles", []).append(startup_profile) or "controller",
    )
    monkeypatch.setattr(
        app_main,
        "_run_interactive_session",
        lambda factory, mode: captured.update({"controller": factory(), "mode": mode}) or 0,
    )

    exit_code = app_main.main([], launch_mode="gui")

    assert exit_code == 0
    assert captured == {"startup_profiles": ["light"], "controller": "controller", "mode": "gui"}


def test_main_relaunches_interactive_session_as_admin_before_gui_start(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(app_main, "_is_running_as_admin", lambda: False, raising=False)
    monkeypatch.setattr(
        app_main,
        "_relaunch_as_admin",
        lambda argv_list: captured.setdefault("argv", list(argv_list)) or 0,
        raising=False,
    )
    monkeypatch.setattr(
        app_main,
        "_run_interactive_session",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("interactive session should not start")),
    )

    exit_code = app_main.main([], launch_mode="gui")

    assert exit_code == 0
    assert captured["argv"] == []


def test_main_skips_relaunch_for_apply_plan_requests(monkeypatch, tmp_path: Path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text('{"changes": [], "startup_changes": []}', encoding="utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setattr(app_main, "_is_running_as_admin", lambda: False, raising=False)
    monkeypatch.setattr(
        app_main,
        "_relaunch_as_admin",
        lambda argv_list: captured.setdefault("argv", list(argv_list)) or 0,
        raising=False,
    )
    monkeypatch.setattr(
        app_main,
        "_controller",
        lambda startup_profile="full": captured.setdefault("startup_profiles", []).append(startup_profile) or "controller",
    )

    def fake_apply_cli_request(controller, args):
        captured["cli"] = (controller, args.apply_plan)
        return 0

    monkeypatch.setattr(app_main, "_apply_cli_request", fake_apply_cli_request)

    exit_code = app_main.main(["--apply-plan", str(plan_path)], launch_mode="gui")

    assert exit_code == 0
    assert "argv" not in captured
    assert captured["startup_profiles"] == ["full"]
    assert captured["cli"][1] == plan_path


class _FakeSplash:
    def __init__(self) -> None:
        self.closed = False
        self.finished_with = None
        self.details: list[str] = []

    def show(self) -> None:
        return

    def close(self) -> None:
        self.closed = True

    def finish(self, window) -> None:
        self.finished_with = window

    def set_detail(self, detail: str) -> None:
        self.details.append(detail)


class _FakeWindow(QWidget):
    created_threads: list[object] = []

    def __init__(self, controller) -> None:
        super().__init__()
        self.controller = controller
        self.was_shown = False
        type(self).created_threads.append(QThread.currentThread())

    def show(self) -> None:
        self.was_shown = True
        super().show()


def test_bootstrap_session_handles_success_on_gui_thread(monkeypatch, qapp, qtbot):
    splash = _FakeSplash()
    created: dict[str, object] = {}

    monkeypatch.setattr(app_main, "_create_loading_splash", lambda _app, message=app_main.LOADING_MESSAGE: splash)
    monkeypatch.setattr(app_main, "TweakifyMainWindow", _FakeWindow)

    session = app_main.BootstrapSession(qapp, lambda: "controller", "gui")
    session.finished.connect(lambda result: created.setdefault("result", result))
    session.start()

    qtbot.waitUntil(lambda: "result" in created, timeout=5000)

    assert created["result"] == 0
    assert session.window is not None
    assert isinstance(session.window, _FakeWindow)
    assert session.window.controller == "controller"
    assert session.window.was_shown is True
    assert splash.finished_with is session.window
    assert _FakeWindow.created_threads[-1] == qapp.thread()
    assert not session.loading_timer.isActive()
    session.worker_thread.wait(1000)


def test_bootstrap_session_prints_loaded_banner_for_console_launch(monkeypatch, qapp, qtbot):
    splash = _FakeSplash()
    created: dict[str, object] = {}

    monkeypatch.setattr(app_main, "_create_loading_splash", lambda _app, message=app_main.LOADING_MESSAGE: splash)
    monkeypatch.setattr(app_main, "TweakifyMainWindow", _FakeWindow)
    monkeypatch.setattr(
        app_main,
        "_print_console_loaded_banner",
        lambda stdout=None: created.setdefault("printed", True),
    )

    session = app_main.BootstrapSession(qapp, lambda: "controller", "console")
    session.finished.connect(lambda result: created.setdefault("result", result))
    session.start()

    qtbot.waitUntil(lambda: "result" in created, timeout=5000)

    assert created["result"] == 0
    assert created["printed"] is True
    session.worker_thread.wait(1000)


def test_bootstrap_session_handles_failure_on_gui_thread(monkeypatch, qapp, qtbot):
    splash = _FakeSplash()
    failure: dict[str, object] = {}

    monkeypatch.setattr(app_main, "_create_loading_splash", lambda _app, message=app_main.LOADING_MESSAGE: splash)
    monkeypatch.setattr(
        app_main.QMessageBox,
        "critical",
        lambda _parent, title, message: failure.setdefault(
            "dialog",
            {
                "title": title,
                "message": message,
                "thread": QThread.currentThread(),
            },
        ),
    )
    monkeypatch.setattr(
        app_main.QTimer,
        "singleShot",
        lambda delay, callback: failure.setdefault("single_shot", {"delay": delay, "callback": callback}),
    )

    session = app_main.BootstrapSession(qapp, lambda: (_ for _ in ()).throw(RuntimeError("boom")), "gui")
    session.finished.connect(lambda result: failure.setdefault("result", result))
    session.start()

    qtbot.waitUntil(lambda: "dialog" in failure and "result" in failure, timeout=5000)

    assert failure["result"] == 1
    assert failure["dialog"]["title"] == "Tweakify Startup Error"
    assert failure["dialog"]["message"] == "boom"
    assert failure["dialog"]["thread"] == qapp.thread()
    assert failure["single_shot"]["delay"] == 0
    assert splash.closed is True
    assert session.window is None
    assert not session.loading_timer.isActive()
    session.worker_thread.wait(1000)
