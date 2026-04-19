from __future__ import annotations

import shutil
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


ROOT = _project_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.copy import ADMIN_PRIVILEGE_NOTE


DATA_DIRS = (
    "snapshots",
    "apply-logs",
    "cache",
    "plans",
    "disabled-startup",
)
RUNTIME_FILES = (
    "Tweakify.py",
    "Tweakify.pyw",
    "requirements.txt",
    "install_requirements.bat",
)
RUNTIME_TOOLS = (
    "nvidiaInspector.exe",
)

def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "legacy.py"),
    )


def build_portable(project_root: Path | str | None = None, output_dir: Path | str | None = None) -> Path:
    root = Path(project_root) if project_root is not None else _project_root()
    destination = Path(output_dir) if output_dir is not None else root / "TweakifyPortable"

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    for file_name in RUNTIME_FILES:
        shutil.copy2(root / file_name, destination / file_name)

    _copy_tree(root / "app", destination / "app")

    tools_destination = destination / "tools"
    tools_destination.mkdir(parents=True, exist_ok=True)
    for tool_name in RUNTIME_TOOLS:
        source = root / "tools" / tool_name
        if source.exists():
            shutil.copy2(source, tools_destination / tool_name)

    (tools_destination / "NVIDIA Profile Inspector").mkdir(parents=True, exist_ok=True)

    data_root = destination / "data"
    for directory_name in DATA_DIRS:
        (data_root / directory_name).mkdir(parents=True, exist_ok=True)

    readme = destination / "README.txt"
    readme.write_text(
        "\n".join(
            [
                "Tweakify Portable",
                "",
                "Prerequisites:",
                "- Python 3.13+ installed or installable through `winget`.",
                "- PySide6 will be installed by `install_requirements.bat`.",
                "- Run `install_requirements.bat` before the first launch.",
                "",
                "Launch:",
                "- Open a command prompt in this folder.",
                "- Run `install_requirements.bat`.",
                "- Run `py Tweakify.py`.",
                "",
                "Administrator privileges:",
                f"- {ADMIN_PRIVILEGE_NOTE}",
                "",
                "Runtime data is stored inside the local `data` folder.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return destination


def main() -> int:
    destination = build_portable()
    print(f"Built portable folder at {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
