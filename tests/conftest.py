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
