from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path


SW_SHOWNORMAL = 1
ERROR_CANCELLED = 1223


class ElevationDeclined(RuntimeError):
    """The user dismissed the UAC prompt, or Windows refused to elevate."""


class ElevationManager:
    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            root = local_app_data / "Tweakify" / "plans"
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write_plan_file(self, payload: dict) -> Path:
        plan_id = str(payload.get("plan_id", uuid.uuid4()))
        path = self.root / f"{Path(plan_id).name}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def _launcher_path(self, launcher_path: Path | str | None = None) -> Path:
        if launcher_path is not None:
            return Path(launcher_path)
        return Path(__file__).resolve().parents[2] / "Tweakify.py"

    def build_apply_command(self, plan_path: Path, python_executable: str | None = None) -> list[str]:
        python_executable = python_executable or sys.executable
        return [python_executable, str(self._launcher_path()), "--apply-plan", str(plan_path)]

    def build_rollback_command(
        self, snapshot_id: str, python_executable: str | None = None
    ) -> list[str]:
        python_executable = python_executable or sys.executable
        return [python_executable, str(self._launcher_path()), "--rollback-snapshot", snapshot_id]

    def launch_elevated(self, command: list[str]) -> None:
        """Start `command` through the UAC prompt.

        ShellExecuteW takes the argument string directly, so paths with spaces or
        apostrophes survive. The old PowerShell `Start-Process -ArgumentList`
        route split "C:\\Users\\Jane Doe\\..." into two arguments and broke on "'".
        """
        executable, arguments = command[0], subprocess.list2cmdline(command[1:])
        shell_execute = getattr(getattr(ctypes, "windll", None), "shell32", None)
        if shell_execute is None:  # pragma: no cover - non-Windows development hosts
            raise ElevationDeclined("Elevation is only available on Windows.")
        result = shell_execute.ShellExecuteW(None, "runas", executable, arguments, None, SW_SHOWNORMAL)
        if int(result) <= 32:
            # ShellExecuteW returns SE_ERR_ACCESSDENIED (5) when the prompt is dismissed.
            raise ElevationDeclined(
                "Administrator permission was not granted, so Tweakify is running without elevation."
            )
