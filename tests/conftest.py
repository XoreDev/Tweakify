import os
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.controller import TweakifyController
from app.platform.adapters import InMemoryPlatformFacade


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONSOLE_LAUNCHER = ROOT / "Tweakify.py"
GUI_LAUNCHER = ROOT / "Tweakify.pyw"


@pytest.fixture(autouse=True)
def _no_real_uac_relaunch(monkeypatch):
    """A test that reached the real relaunch would pop a UAC prompt and hang the run."""
    import app.__main__ as app_main

    def refuse(_argv):
        raise AssertionError("tests must not trigger a real UAC relaunch; patch _is_running_as_admin")

    monkeypatch.setattr(app_main, "_relaunch_as_admin", refuse)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def build_controller(tmp_path: Path, platform=None) -> TweakifyController:
    return TweakifyController(
        platform=platform or InMemoryPlatformFacade(),
        storage_root=tmp_path,
    )
