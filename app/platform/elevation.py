from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from app.platform.processes import hidden_process_kwargs


class ElevationManager:
    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            root = local_app_data / "Tweakify" / "plans"
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write_plan_file(self, payload: dict) -> Path:
        plan_id = payload.get("plan_id", str(uuid.uuid4()))
        path = self.root / f"{plan_id}.json"
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
        quoted = ", ".join(f"'{item}'" for item in command[1:])
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Start-Process -FilePath '{command[0]}' -ArgumentList {quoted} -Verb RunAs",
            ],
            **hidden_process_kwargs(),
        )
