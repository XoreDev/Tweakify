from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.domain.models import DependencyInstallResult, MachineContext, SnapshotWriter, StartupEntry
from app.platform.processes import hidden_process_kwargs


class InMemoryPlatformFacade:
    def __init__(self, is_admin: bool = False) -> None:
        self.is_admin = is_admin
        self._probe_cache: dict[tuple[object, ...], Any] | None = None
        self._probe_cache_depth = 0
        self.registry: dict[tuple[str, str], Any] = {}
        self.services: dict[str, dict[str, Any]] = {
            "XblAuthManager": {"start_mode": "manual", "running": True},
            "XblGameSave": {"start_mode": "manual", "running": True},
            "bthserv": {"start_mode": "manual", "running": True},
            "BITS": {"start_mode": "auto", "running": True},
            "DiagTrack": {"start_mode": "auto", "running": True},
        }
        self.interface_values: dict[str, dict[str, Any]] = {
            "ethernet0": {},
        }
        self.tcp_globals: dict[str, str] = {
            "autotuninglevel": "normal",
            "heuristics": "enabled",
            "dca": "disabled",
            "rss": "enabled",
            "template": "internet",
            "chimney": "disabled",
            "ecncapability": "default",
        }
        self.command_log: list[str] = []
        self.nvidia_path: Path | None = None
        self.profile_inspector_path: Path | None = None
        self.dependency_overrides: dict[str, Path] = {}
        self.diagnostics = {
            "startup_count": 8,
            "top_idle_cpu_users": ["Discord", "Steam", "SearchIndexer"],
            "ram_pressure": "42%",
            "disk_free_percent": "58%",
            "drive_type": "SSD",
            "pending_updates": "None",
            "vbs_status": "On",
            "memory_integrity": "On",
            "indexing_state": "Running",
            "delivery_optimization": "Local network only",
        }
        self.bluetooth_devices = 0
        self.oem_vendor = "Generic"
        self.app_theme_mode = "dark"
        self.pointer_precision_enabled = True
        self.system_parameters: dict[str, Any] = {
            "enhance_pointer_precision": True,
            "mouse_trails": 0,
            "double_click_speed": 500,
            "key_delay": 1,
        }
        self.power_plan = "Balanced"
        self.display_refresh_rates = [60, 120, 144]
        self.current_refresh_rate = 60
        self.startup_entries: list[dict[str, Any]] = [
            {
                "id": self._startup_registry_id("user", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run", "Discord"),
                "name": "Discord",
                "location": "Run",
                "enabled": True,
                "command": "Discord.exe --start-minimized",
                "source_kind": "registry",
                "scope": "user",
                "registry_path": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                "value_name": "Discord",
            },
            {
                "id": self._startup_registry_id("user", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run", "Steam"),
                "name": "Steam",
                "location": "Run",
                "enabled": True,
                "command": "steam.exe -silent",
                "source_kind": "registry",
                "scope": "user",
                "registry_path": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                "value_name": "Steam",
            },
            {
                "id": self._startup_registry_id("user", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run", "OneDrive"),
                "name": "OneDrive",
                "location": "Run",
                "enabled": True,
                "command": "OneDrive.exe /background",
                "source_kind": "registry",
                "scope": "user",
                "registry_path": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                "value_name": "OneDrive",
            },
        ]
        self.scheduled_tasks: dict[str, dict[str, Any]] = {
            r"\Microsoft\Windows\Application Experience\Microsoft Compatibility Appraiser": {
                "name": r"\Microsoft\Windows\Application Experience\Microsoft Compatibility Appraiser",
                "enabled": True,
            },
            r"\Microsoft\Windows\Application Experience\ProgramDataUpdater": {
                "name": r"\Microsoft\Windows\Application Experience\ProgramDataUpdater",
                "enabled": True,
            },
            r"\Microsoft\Windows\Customer Experience Improvement Program\Consolidator": {
                "name": r"\Microsoft\Windows\Customer Experience Improvement Program\Consolidator",
                "enabled": True,
            },
            r"\Microsoft\Windows\Customer Experience Improvement Program\UsbCeip": {
                "name": r"\Microsoft\Windows\Customer Experience Improvement Program\UsbCeip",
                "enabled": True,
            },
        }
        self.net_features: dict[str, bool] = {"lso": True}
        self.opened_urls: list[str] = []

    def snapshot_writer(self) -> SnapshotWriter:
        return SnapshotWriter()

    @contextmanager
    def probe_session(self):
        self._probe_cache_depth += 1
        if self._probe_cache is None:
            self._probe_cache = {}
        try:
            yield
        finally:
            self._probe_cache_depth -= 1
            if self._probe_cache_depth == 0:
                self._probe_cache = None

    def _cached_probe(self, key: tuple[object, ...], loader):
        if self._probe_cache is None:
            return loader()
        if key not in self._probe_cache:
            self._probe_cache[key] = loader()
        return self._probe_cache[key]

    def set_dependency_path(self, name: str, path: str | Path | None) -> None:
        if path:
            self.dependency_overrides[name] = Path(path)
        elif name in self.dependency_overrides:
            self.dependency_overrides.pop(name, None)

    def bootstrap_machine_context(self) -> MachineContext:
        return MachineContext(
            machine_name="TESTBOX",
            windows_build=26100,
            edition="Professional",
            oem_vendor="Unknown",
            is_admin=self.is_admin,
            nvidia_inspector_path=None,
            bluetooth_devices=0,
        )

    def machine_context(self) -> MachineContext:
        return self._cached_probe(
            ("machine_context",),
            lambda: MachineContext(
                machine_name="TESTBOX",
                windows_build=26100,
                edition="Professional",
                oem_vendor=self.oem_vendor,
                is_admin=self.is_admin,
                nvidia_inspector_path=str((self.dependency_overrides.get("nvidiaInspector.exe") or self.nvidia_path))
                if (self.dependency_overrides.get("nvidiaInspector.exe") or self.nvidia_path)
                else None,
                bluetooth_devices=self.bluetooth_devices,
            ),
        )

    def diagnostic_probe(self, startup_count: int | None = None) -> dict[str, Any]:
        data = self.diagnostics.copy()
        data["startup_count"] = startup_count if startup_count is not None else self.startup_inventory()["count"]
        return data

    def registry_get(self, path: str, name: str) -> Any:
        return self.registry.get((path, name))

    def registry_set(self, path: str, name: str, value: Any, value_type: str = "REG_DWORD") -> None:
        self.registry[(path, name)] = value

    def registry_delete(self, path: str, name: str) -> None:
        self.registry.pop((path, name), None)

    def service_get(self, name: str) -> dict[str, Any]:
        service = self._cached_probe(
            ("service_get", name),
            lambda: self.services.setdefault(name, {"start_mode": "manual", "running": False}).copy(),
        )
        return dict(service)

    def service_set(self, name: str, start_mode: str) -> None:
        self.services.setdefault(name, {"start_mode": "manual", "running": False})["start_mode"] = start_mode

    def service_stop(self, name: str) -> None:
        self.services.setdefault(name, {"start_mode": "manual", "running": False})["running"] = False

    def service_start(self, name: str) -> None:
        self.services.setdefault(name, {"start_mode": "manual", "running": False})["running"] = True

    def scheduled_task_get(self, name: str) -> dict[str, Any] | None:
        task = self._cached_probe(("scheduled_task_get", name), lambda: self.scheduled_tasks.get(name))
        return task.copy() if task else None

    def scheduled_task_set(self, name: str, enabled: bool) -> None:
        self.scheduled_tasks.setdefault(name, {"name": name, "enabled": True})["enabled"] = enabled

    def get_interface_value(self, name: str) -> dict[str, Any]:
        values = self._cached_probe(
            ("get_interface_value", name),
            lambda: {adapter: adapter_values.get(name) for adapter, adapter_values in self.interface_values.items()},
        )
        return dict(values)

    def set_interface_value(self, name: str, value: Any) -> None:
        for adapter in self.interface_values:
            self.interface_values[adapter][name] = value

    def clear_interface_value(self, name: str) -> None:
        for adapter in self.interface_values:
            self.interface_values[adapter].pop(name, None)

    def get_tcp_global(self, key: str) -> str | None:
        return self._cached_probe(("get_tcp_global", key), lambda: self.tcp_globals.get(key))

    def set_tcp_global(self, key: str, value: str) -> None:
        self.tcp_globals[key] = value
        self.command_log.append(f"netsh:{key}={value}")

    def system_parameter_get(self, name: str) -> Any:
        if name == "enhance_pointer_precision":
            return self.pointer_precision_enabled
        return self.system_parameters.get(name)

    def system_parameter_set(self, name: str, value: Any) -> None:
        self.system_parameters[name] = value
        if name == "enhance_pointer_precision":
            self.pointer_precision_enabled = bool(value)
        self.command_log.append(f"spi:{name}={value}")

    def broadcast_setting_change(self, key: str) -> None:
        self.command_log.append(f"broadcast:{key}")

    def refresh_explorer(self) -> None:
        self.command_log.append("explorer:refresh")

    def power_get_active_plan(self) -> dict[str, Any]:
        plan = self._cached_probe(("power_get_active_plan",), lambda: {"name": self.power_plan})
        return dict(plan)

    def power_set_active_plan(self, name: str) -> None:
        self.power_plan = name
        self.command_log.append(f"power:{name}")

    def display_get_current_refresh_rate(self) -> int:
        return self._cached_probe(("display_get_current_refresh_rate",), lambda: self.current_refresh_rate)

    def display_get_highest_refresh_rate(self) -> int:
        return self._cached_probe(("display_get_highest_refresh_rate",), lambda: max(self.display_refresh_rates))

    def display_set_refresh_rate(self, value: int) -> None:
        self.current_refresh_rate = value
        self.command_log.append(f"display:{value}")

    def startup_inventory(self) -> dict[str, Any]:
        items = [StartupEntry.from_dict(item) if not isinstance(item, StartupEntry) else item for item in self.startup_entries]
        counts: dict[str, int] = {}
        for item in items:
            key = item.name.casefold()
            counts[key] = counts.get(key, 0) + 1
        duplicates = sorted(
            {item.name for item in items if counts[item.name.casefold()] > 1}
        )
        normalized = [
            StartupEntry(
                id=item.id,
                name=item.name,
                location=item.location,
                enabled=item.enabled,
                status_source=getattr(
                    item,
                    "status_source",
                    "tweakify_disabled" if item.managed_by_tweakify and not item.enabled else "active",
                ),
                command=item.command,
                duplicate=item.name in duplicates,
                source_kind=item.source_kind,
                scope=item.scope,
                registry_path=item.registry_path,
                value_name=item.value_name,
                file_path=item.file_path,
                original_path=item.original_path,
                managed_by_tweakify=item.managed_by_tweakify,
            )
            for item in items
        ]
        normalized.sort(key=lambda item: (0 if item.enabled else 1, item.name.casefold(), item.location.casefold()))
        return {
            "count": len(normalized),
            "duplicates": duplicates,
            "items": normalized,
        }

    def startup_entry_set_enabled(self, entry_id: str, enabled: bool) -> None:
        for index, raw_item in enumerate(self.startup_entries):
            item = StartupEntry.from_dict(raw_item) if not isinstance(raw_item, StartupEntry) else raw_item
            if item.id != entry_id:
                continue
            item.enabled = enabled
            item.managed_by_tweakify = not enabled
            item.status_source = "active" if enabled else "tweakify_disabled"
            self.startup_entries[index] = item.to_dict()
            self.command_log.append(f"startup-entry:{entry_id}={enabled}")
            return

    def _startup_registry_id(self, scope: str, path: str, name: str) -> str:
        return f"registry:{scope}:{path}:{name}"

    def _startup_folder_id(self, scope: str, original_path: str) -> str:
        return f"startup-folder:{scope}:{original_path}"

    def run_command(self, command: list[str], description: str = "") -> None:
        self.command_log.append(" ".join(command) if not description else f"{description}: {' '.join(command)}")

    def detect_nvidia_inspector(self, base_dir: Path | str | None = None) -> Path | None:
        return self._cached_probe(
            ("detect_nvidia_inspector", str(base_dir) if base_dir else ""),
            lambda: self._detect_nvidia_inspector_uncached(base_dir),
        )

    def _detect_nvidia_inspector_uncached(self, base_dir: Path | str | None = None) -> Path | None:
        override = self.dependency_overrides.get("nvidiaInspector.exe")
        if override and override.exists():
            self.nvidia_path = override
            return override
        root = Path(base_dir) if base_dir else None
        if root:
            direct = root / "nvidiaInspector.exe"
            if direct.exists():
                self.nvidia_path = direct
                return direct
        detected = self.detect_nvidia_inspector_known_locations(base_dir)
        if detected:
            self.nvidia_path = detected
            return detected
        return self.nvidia_path

    def detect_nvidia_inspector_known_locations(self, base_dir: Path | str | None = None) -> Path | None:
        return self._cached_probe(
            ("detect_nvidia_inspector_known_locations", str(base_dir) if base_dir else ""),
            lambda: self._detect_nvidia_inspector_known_locations_uncached(base_dir),
        )

    def _detect_nvidia_inspector_known_locations_uncached(self, base_dir: Path | str | None = None) -> Path | None:
        override = self.dependency_overrides.get("nvidiaInspector.exe")
        if override and override.exists():
            self.nvidia_path = override
            return override
        candidates: list[Path] = []
        if base_dir:
            root = Path(base_dir)
            candidates.extend(
                [
                    root / "nvidiaInspector.exe",
                    root / "nvidiaInspector" / "nvidiaInspector.exe",
                    root / "tools" / "NVIDIA Inspector" / "nvidiaInspector.exe",
                ]
            )
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        candidates.append(local_app_data / "Tweakify" / "tools" / "NVIDIA Inspector" / "nvidiaInspector.exe")
        for candidate in candidates:
            if candidate.exists():
                self.nvidia_path = candidate
                return candidate
        return None

    def invoke_nvidia(self, args: list[str]) -> None:
        override = self.dependency_overrides.get("nvidiaInspector.exe")
        exe = override or self.nvidia_path
        if not exe:
            raise FileNotFoundError("nvidiaInspector.exe is unavailable")
        self.command_log.append(f"{Path(exe).name} {' '.join(args)}")

    def create_restore_point(self, description: str) -> bool:
        self.command_log.append(f"restore-point:{description}")
        return True

    def open_task_manager(self) -> None:
        self.command_log.append("taskmgr")

    def system_theme_mode(self) -> str:
        return self.app_theme_mode

    def open_external_url(self, url: str) -> None:
        self.opened_urls.append(url)

    def detect_nvidia_profile_inspector_known_locations(self, base_dir: Path | str | None = None) -> Path | None:
        return self._cached_probe(
            ("detect_nvidia_profile_inspector_known_locations", str(base_dir) if base_dir else ""),
            lambda: self._detect_nvidia_profile_inspector_known_locations_uncached(base_dir),
        )

    def _detect_nvidia_profile_inspector_known_locations_uncached(
        self, base_dir: Path | str | None = None
    ) -> Path | None:
        override = self.dependency_overrides.get("nvidiaProfileInspector.exe")
        if override and override.exists():
            self.profile_inspector_path = override
            return override
        candidates: list[Path] = []
        if self.profile_inspector_path and self.profile_inspector_path.exists():
            candidates.append(self.profile_inspector_path)
        root = Path(base_dir) if base_dir else None
        if root:
            candidates.extend(
                [
                    root / "nvidiaProfileInspector.exe",
                    root / "NVIDIA Profile Inspector" / "nvidiaProfileInspector.exe",
                    root / "tools" / "NVIDIA Profile Inspector" / "nvidiaProfileInspector.exe",
                ]
            )
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        candidates.append(local_app_data / "Tweakify" / "tools" / "NVIDIA Profile Inspector" / "nvidiaProfileInspector.exe")
        for candidate in candidates:
            if candidate.exists():
                self.profile_inspector_path = candidate
                return candidate
        return None

    def download_nvidia_profile_inspector(self) -> DependencyInstallResult:
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        target_dir = local_app_data / "Tweakify" / "tools" / "NVIDIA Profile Inspector"
        target_dir.mkdir(parents=True, exist_ok=True)
        exe_path = target_dir / "nvidiaProfileInspector.exe"
        exe_path.write_text("stub", encoding="utf-8")
        self.profile_inspector_path = exe_path
        return DependencyInstallResult(
            dependency_name="NVIDIA Profile Inspector",
            success=True,
            message="Downloaded NVIDIA Profile Inspector into the managed tools folder.",
            installed_path=str(exe_path),
        )

    def net_adapter_feature_get(self, feature: str) -> bool | None:
        return self._cached_probe(("net_adapter_feature_get", feature), lambda: self.net_features.get(feature))

    def net_adapter_feature_set(self, feature: str, enabled: bool) -> None:
        self.net_features[feature] = enabled
        self.command_log.append(f"net-feature:{feature}={enabled}")


class WindowsPlatformFacade:
    def __init__(
        self,
        workspace_root: Path | str | None = None,
        data_root: Path | str | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root or Path(__file__).resolve().parents[2])
        self._probe_cache: dict[tuple[object, ...], Any] | None = None
        self._probe_cache_depth = 0
        self._snapshot_writer_factory = SnapshotWriter
        self.dependency_overrides: dict[str, Path] = {}
        self.local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        self.tweakify_root = Path(data_root) if data_root is not None else self.local_app_data / "Tweakify"
        self.tools_root = self.workspace_root / "tools"
        self.disabled_startup_dir = self.tweakify_root / "disabled-startup"
        self.profile_inspector_dir = self.tools_root / "NVIDIA Profile Inspector"
        self.tools_root.mkdir(parents=True, exist_ok=True)
        self.disabled_startup_dir.mkdir(parents=True, exist_ok=True)

    def snapshot_writer(self) -> SnapshotWriter:
        return self._snapshot_writer_factory()

    @contextmanager
    def probe_session(self):
        self._probe_cache_depth += 1
        if self._probe_cache is None:
            self._probe_cache = {}
        try:
            yield
        finally:
            self._probe_cache_depth -= 1
            if self._probe_cache_depth == 0:
                self._probe_cache = None

    def _cached_probe(self, key: tuple[object, ...], loader):
        if self._probe_cache is None:
            return loader()
        if key not in self._probe_cache:
            self._probe_cache[key] = loader()
        return self._probe_cache[key]

    def _run_hidden(self, command: list[str], **kwargs):
        return subprocess.run(command, **hidden_process_kwargs(), **kwargs)

    def set_dependency_path(self, name: str, path: str | Path | None) -> None:
        if path:
            self.dependency_overrides[name] = Path(path)
        elif name in self.dependency_overrides:
            self.dependency_overrides.pop(name, None)

    def system_theme_mode(self) -> str:
        value = self.registry_get(
            r"HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            "AppsUseLightTheme",
        )
        return "light" if str(value or "0") == "1" else "dark"

    def bootstrap_machine_context(self) -> MachineContext:
        edition = self.registry_get(
            r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion",
            "EditionID",
        ) or "Unknown"
        return MachineContext(
            machine_name=os.environ.get("COMPUTERNAME", socket.gethostname()),
            windows_build=sys.getwindowsversion().build,
            edition=str(edition),
            oem_vendor="Unknown",
            is_admin=self.is_admin(),
            nvidia_inspector_path=None,
            bluetooth_devices=0,
        )

    def machine_context(self) -> MachineContext:
        return self._cached_probe(("machine_context",), self._machine_context_uncached)

    def _machine_context_uncached(self) -> MachineContext:
        nvidia_path = self.detect_nvidia_inspector()
        return MachineContext(
            machine_name=os.environ.get("COMPUTERNAME", socket.gethostname()),
            windows_build=sys.getwindowsversion().build,
            edition=str(
                self.registry_get(
                    r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion",
                    "EditionID",
                )
                or "Unknown"
            ),
            oem_vendor=str(
                self._read_cim_property("(Get-CimInstance Win32_ComputerSystem).Manufacturer") or "Unknown"
            ).strip(),
            is_admin=self.is_admin(),
            nvidia_inspector_path=str(nvidia_path) if nvidia_path else None,
            bluetooth_devices=self.bluetooth_device_count(),
        )

    def diagnostic_probe(self, startup_count: int | None = None) -> dict[str, Any]:
        system_drive = os.environ.get("SystemDrive", "C:")
        if not system_drive.endswith("\\"):
            system_drive = f"{system_drive}\\"
        usage = shutil.disk_usage(Path(system_drive))
        total = usage[0]
        free = usage[2]
        disk_percent = f"{int((free / total) * 100)}%"
        pending_updates = "Pending reboot" if self.registry_key_exists(
            r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
        ) else "None"
        vbs_status = "On" if self.registry_get(
            r"HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard",
            "EnableVirtualizationBasedSecurity",
        ) else "Off"
        memory_integrity = "On" if self.registry_get(
            r"HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity",
            "Enabled",
        ) else "Off"
        return {
            "startup_count": startup_count if startup_count is not None else self.startup_entry_count(),
            "top_idle_cpu_users": self.top_cpu_users(),
            "ram_pressure": self.memory_pressure(),
            "disk_free_percent": disk_percent,
            "drive_type": self.system_drive_type(),
            "pending_updates": pending_updates,
            "vbs_status": vbs_status,
            "memory_integrity": memory_integrity,
            "indexing_state": self.service_get("WSearch")["start_mode"].title(),
            "delivery_optimization": self.service_get("DoSvc")["start_mode"].title(),
        }

    def startup_entry_count(self) -> int:
        return self.startup_inventory()["count"]

    def registry_get(self, path: str, name: str) -> Any:
        import winreg

        hive, subkey = self._split_hive(path)
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return value
        except FileNotFoundError:
            return None

    def registry_set(self, path: str, name: str, value: Any, value_type: str = "REG_DWORD") -> None:
        import winreg

        hive, subkey = self._split_hive(path)
        reg_type = getattr(winreg, value_type, winreg.REG_DWORD)
        with winreg.CreateKeyEx(hive, subkey, 0, access=winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, name, 0, reg_type, value)

    def registry_delete(self, path: str, name: str) -> None:
        import winreg

        hive, subkey = self._split_hive(path)
        try:
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return
        except OSError:
            return

    def registry_key_exists(self, path: str) -> bool:
        import winreg

        hive, subkey = self._split_hive(path)
        try:
            with winreg.OpenKey(hive, subkey):
                return True
        except FileNotFoundError:
            return False

    def registry_value_map(self, path: str) -> dict[str, Any]:
        import winreg

        hive, subkey = self._split_hive(path)
        values: dict[str, Any] = {}
        try:
            with winreg.OpenKey(hive, subkey) as key:
                index = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    values[name] = value
                    index += 1
        except FileNotFoundError:
            return {}
        return values

    def service_get(self, name: str) -> dict[str, Any]:
        result = self._cached_probe(("service_get", name), lambda: self._service_get_uncached(name))
        return dict(result)

    def _service_get_uncached(self, name: str) -> dict[str, Any]:
        qc = self._run_hidden(
            ["sc", "qc", name],
            capture_output=True,
            text=True,
            check=False,
        )
        query = self._run_hidden(
            ["sc", "query", name],
            capture_output=True,
            text=True,
            check=False,
        )
        start_mode = "unknown"
        for line in qc.stdout.splitlines():
            if "START_TYPE" in line:
                if "DISABLED" in line:
                    start_mode = "disabled"
                elif "DEMAND_START" in line:
                    start_mode = "manual"
                elif "AUTO_START" in line:
                    start_mode = "auto"
                break
        running = "RUNNING" in query.stdout
        return {"start_mode": start_mode, "running": running}

    def service_set(self, name: str, start_mode: str) -> None:
        mapping = {"manual": "demand", "auto": "auto", "disabled": "disabled"}
        self._run_hidden(["sc", "config", name, f"start= {mapping[start_mode]}"], check=False)

    def service_stop(self, name: str) -> None:
        self._run_hidden(["sc", "stop", name], check=False)

    def service_start(self, name: str) -> None:
        self._run_hidden(["sc", "start", name], check=False)

    def scheduled_task_get(self, name: str) -> dict[str, Any] | None:
        task = self._cached_probe(("scheduled_task_get", name), lambda: self._scheduled_task_get_uncached(name))
        return dict(task) if task else None

    def _scheduled_task_get_uncached(self, name: str) -> dict[str, Any] | None:
        task_path, task_name = self._split_task_name(name)
        script = (
            f"$task = Get-ScheduledTask -TaskPath '{task_path}' -TaskName '{task_name}' -ErrorAction SilentlyContinue; "
            "if ($task) { if ($task.Settings.Enabled) { 'Enabled' } else { 'Disabled' } }"
        )
        output = self._run_hidden(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if not output:
            return None
        return {"name": name, "enabled": output.lower() == "enabled"}

    def scheduled_task_set(self, name: str, enabled: bool) -> None:
        task_path, task_name = self._split_task_name(name)
        command = "Enable-ScheduledTask" if enabled else "Disable-ScheduledTask"
        script = (
            f"{command} -TaskPath '{task_path}' -TaskName '{task_name}' -ErrorAction SilentlyContinue | Out-Null"
        )
        self._run_hidden(["powershell", "-NoProfile", "-Command", script], check=False)

    def get_interface_value(self, name: str) -> dict[str, Any]:
        values = self._cached_probe(("get_interface_value", name), lambda: self._get_interface_value_uncached(name))
        return dict(values)

    def _get_interface_value_uncached(self, name: str) -> dict[str, Any]:
        import winreg

        result: dict[str, Any] = {}
        root_hive, root_subkey = self._split_hive(
            r"HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
        )
        for subkey_name in self._iter_registry_subkeys(root_hive, root_subkey):
            sub_path = f"{root_subkey}\\{subkey_name}"
            try:
                with winreg.OpenKey(root_hive, sub_path) as sub_key:
                    value, _ = winreg.QueryValueEx(sub_key, name)
                    result[subkey_name] = value
            except FileNotFoundError:
                continue
            except OSError:
                continue
        return result

    def set_interface_value(self, name: str, value: Any) -> None:
        import winreg

        root_hive, root_subkey = self._split_hive(
            r"HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
        )
        for subkey_name in self._iter_registry_subkeys(root_hive, root_subkey):
            sub_path = f"{root_subkey}\\{subkey_name}"
            try:
                with winreg.CreateKeyEx(root_hive, sub_path, 0, access=winreg.KEY_WRITE) as sub_key:
                    winreg.SetValueEx(sub_key, name, 0, winreg.REG_DWORD, value)
            except OSError:
                continue

    def clear_interface_value(self, name: str) -> None:
        import winreg

        root_hive, root_subkey = self._split_hive(
            r"HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
        )
        for subkey_name in self._iter_registry_subkeys(root_hive, root_subkey):
            sub_path = f"{root_subkey}\\{subkey_name}"
            try:
                with winreg.OpenKey(root_hive, sub_path, 0, winreg.KEY_SET_VALUE) as sub_key:
                    winreg.DeleteValue(sub_key, name)
            except OSError:
                continue

    def get_tcp_global(self, key: str) -> str | None:
        return self._cached_probe(("get_tcp_global", key), lambda: self._get_tcp_global_uncached(key))

    def _get_tcp_global_uncached(self, key: str) -> str | None:
        output = self._run_hidden(
            ["netsh", "int", "tcp", "show", "global"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        mapping = {
            "autotuninglevel": "Receive Window Auto-Tuning Level",
            "chimney": "Chimney Offload State",
            "dca": "Direct Cache Access (DCA)",
            "rss": "Receive-Side Scaling State",
            "ecncapability": "ECN Capability",
        }
        label = mapping.get(key)
        if not label:
            return None
        for line in output.splitlines():
            if label in line:
                return line.split(":", 1)[-1].strip().lower()
        return None

    def set_tcp_global(self, key: str, value: str) -> None:
        if key == "heuristics":
            self._run_hidden(["netsh", "int", "tcp", "set", "heuristics", value], check=False)
            return
        if key == "template":
            self._run_hidden(
                ["netsh", "int", "tcp", "set", "supplemental", f"template={value}"],
                check=False,
            )
            return
        self._run_hidden(["netsh", "int", "tcp", "set", "global", f"{key}={value}"], check=False)

    def system_parameter_get(self, name: str) -> Any:
        mapping = {
            "enhance_pointer_precision": (
                r"HKCU\Control Panel\Mouse",
                "MouseSpeed",
                lambda value: str(value or "1") != "0",
            ),
            "mouse_trails": (
                r"HKCU\Control Panel\Mouse",
                "MouseTrails",
                lambda value: int(str(value or "0")),
            ),
            "double_click_speed": (
                r"HKCU\Control Panel\Mouse",
                "DoubleClickSpeed",
                lambda value: int(str(value or "500")),
            ),
            "key_delay": (
                r"HKCU\Control Panel\Keyboard",
                "KeyboardDelay",
                lambda value: int(str(value or "1")),
            ),
        }
        if name not in mapping:
            return None
        path, value_name, transform = mapping[name]
        return transform(self.registry_get(path, value_name))

    def system_parameter_set(self, name: str, value: Any) -> None:
        if name == "enhance_pointer_precision":
            speed = 1 if value else 0
            thresholds = (6, 10, speed) if value else (0, 0, 0)
            array_type = ctypes.c_int * 3
            ctypes.windll.user32.SystemParametersInfoW(
                0x0004,
                0,
                array_type(*thresholds),
                0x01 | 0x02,
            )
            self.registry_set(r"HKCU\Control Panel\Mouse", "MouseSpeed", str(speed), "REG_SZ")
            self.registry_set(r"HKCU\Control Panel\Mouse", "MouseThreshold1", str(thresholds[0]), "REG_SZ")
            self.registry_set(r"HKCU\Control Panel\Mouse", "MouseThreshold2", str(thresholds[1]), "REG_SZ")
            return
        if name == "mouse_trails":
            ctypes.windll.user32.SystemParametersInfoW(0x005D, int(value), None, 0x01 | 0x02)
            self.registry_set(r"HKCU\Control Panel\Mouse", "MouseTrails", str(value), "REG_SZ")
            return
        if name == "double_click_speed":
            ctypes.windll.user32.SetDoubleClickTime(int(value))
            self.registry_set(r"HKCU\Control Panel\Mouse", "DoubleClickSpeed", str(value), "REG_SZ")
            return
        if name == "key_delay":
            ctypes.windll.user32.SystemParametersInfoW(0x0017, int(value), None, 0x01 | 0x02)
            self.registry_set(r"HKCU\Control Panel\Keyboard", "KeyboardDelay", str(value), "REG_SZ")

    def broadcast_setting_change(self, key: str) -> None:
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            ctypes.c_wchar_p(key),
            SMTO_ABORTIFHUNG,
            3000,
            ctypes.byref(result),
        )

    def refresh_explorer(self) -> None:
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
        self.broadcast_setting_change("ShellState")

    def power_get_active_plan(self) -> dict[str, Any]:
        plan = self._cached_probe(("power_get_active_plan",), self._power_get_active_plan_uncached)
        return dict(plan)

    def _power_get_active_plan_uncached(self) -> dict[str, Any]:
        output = self._run_hidden(
            ["powercfg", "/GETACTIVESCHEME"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        match = re.search(r"GUID:\s*([A-Fa-f0-9\-]+)\s+\((.+)\)", output)
        if not match:
            return {"name": "Balanced"}
        return {"guid": match.group(1), "name": match.group(2)}

    def power_set_active_plan(self, name: str) -> None:
        aliases = {
            "balanced": "SCHEME_BALANCED",
            "high performance": "SCHEME_MIN",
            "power saver": "SCHEME_MAX",
            "ultimate performance": "e9a42b02-d5df-448d-aa00-03f14749eb61",
        }
        token = aliases.get(name.lower(), name)
        self._run_hidden(["powercfg", "/S", token], check=False)

    def display_get_current_refresh_rate(self) -> int | None:
        return self._cached_probe(
            ("display_get_current_refresh_rate",),
            self._display_get_current_refresh_rate_uncached,
        )

    def _display_get_current_refresh_rate_uncached(self) -> int | None:
        devmode = self._devmode()
        ENUM_CURRENT_SETTINGS = -1
        if not ctypes.windll.user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(devmode)):
            return None
        return int(devmode.dmDisplayFrequency)

    def display_get_highest_refresh_rate(self) -> int | None:
        return self._cached_probe(
            ("display_get_highest_refresh_rate",),
            self._display_get_highest_refresh_rate_uncached,
        )

    def _display_get_highest_refresh_rate_uncached(self) -> int | None:
        index = 0
        highest = None
        while True:
            devmode = self._devmode()
            if not ctypes.windll.user32.EnumDisplaySettingsW(None, index, ctypes.byref(devmode)):
                break
            highest = max(highest or 0, int(devmode.dmDisplayFrequency))
            index += 1
        return highest

    def display_set_refresh_rate(self, value: int) -> None:
        devmode = self._devmode()
        ENUM_CURRENT_SETTINGS = -1
        DM_DISPLAYFREQUENCY = 0x00400000
        if not ctypes.windll.user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(devmode)):
            return
        devmode.dmFields |= DM_DISPLAYFREQUENCY
        devmode.dmDisplayFrequency = int(value)
        ctypes.windll.user32.ChangeDisplaySettingsW(ctypes.byref(devmode), 0)

    def startup_inventory(self) -> dict[str, Any]:
        items_by_id: dict[str, StartupEntry] = {}
        for path, location, scope in [
            (r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run", "Run", "user"),
            (r"HKLM\Software\Microsoft\Windows\CurrentVersion\Run", "Run (Machine)", "machine"),
        ]:
            approval_values = self.registry_value_map(self._startup_approved_registry_path(scope))
            for name, command in self.registry_value_map(path).items():
                status_source = self._startup_status_source(approval_values.get(name))
                entry = StartupEntry(
                    id=self._startup_registry_id(scope, path, name),
                    name=name,
                    location=location,
                    enabled=status_source == "active",
                    status_source=status_source,
                    command=str(command),
                    source_kind="registry",
                    scope=scope,
                    registry_path=path,
                    value_name=name,
                )
                items_by_id[entry.id] = entry
        for path, location, scope in [
            (r"HKCU\Software\Tweakify\DisabledStartup\Run", "Run", "user"),
            (r"HKLM\Software\Tweakify\DisabledStartup\Run", "Run (Machine)", "machine"),
        ]:
            for name, command in self.registry_value_map(path).items():
                entry = StartupEntry(
                    id=self._startup_registry_id(scope, self._active_registry_path(scope), name),
                    name=name,
                    location=location,
                    enabled=False,
                    status_source="tweakify_disabled",
                    command=str(command),
                    source_kind="registry",
                    scope=scope,
                    registry_path=self._active_registry_path(scope),
                    value_name=name,
                    managed_by_tweakify=True,
                )
                items_by_id.setdefault(entry.id, entry)
        for folder, location, scope in [
            (Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup", "Startup Folder", "user"),
            (Path(os.environ.get("ProgramData", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup", "Startup Folder (Machine)", "machine"),
        ]:
            if not folder.exists():
                continue
            approval_values = self.registry_value_map(self._startup_approved_folder_path(scope))
            for item in folder.iterdir():
                status_source = self._startup_status_source(approval_values.get(item.name))
                entry = StartupEntry(
                    id=self._startup_folder_id(scope, str(item)),
                    name=item.stem,
                    location=location,
                    enabled=status_source == "active",
                    status_source=status_source,
                    command=str(item),
                    source_kind="startup_folder",
                    scope=scope,
                    file_path=str(item),
                    original_path=str(item),
                )
                items_by_id[entry.id] = entry
        for metadata_path in self._disabled_startup_metadata_paths():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            original_path = metadata.get("original_path", "")
            disabled_path = metadata.get("disabled_path", "")
            entry = StartupEntry(
                id=self._startup_folder_id(metadata.get("scope", "user"), original_path),
                name=metadata.get("name", Path(original_path).stem or metadata_path.stem),
                location=metadata.get("location", "Startup Folder"),
                enabled=False,
                status_source="tweakify_disabled",
                command=original_path,
                source_kind="startup_folder",
                scope=metadata.get("scope", "user"),
                file_path=disabled_path,
                original_path=original_path,
                managed_by_tweakify=True,
            )
            items_by_id.setdefault(entry.id, entry)
        items = list(items_by_id.values())
        name_counts: dict[str, int] = {}
        for item in items:
            key = item.name.casefold()
            name_counts[key] = name_counts.get(key, 0) + 1
        duplicates = sorted({item.name for item in items if name_counts[item.name.casefold()] > 1})
        for item in items:
            item.duplicate = item.name in duplicates
        items.sort(key=lambda item: (0 if item.enabled else 1, item.name.casefold(), item.location.casefold()))
        return {"count": len(items), "duplicates": duplicates, "items": items}

    def startup_entry_set_enabled(self, entry_id: str, enabled: bool) -> None:
        entry = next((item for item in self.startup_inventory()["items"] if item.id == entry_id), None)
        if entry is None or entry.enabled == enabled:
            return
        if entry.source_kind == "registry":
            self._set_registry_startup_entry(entry, enabled)
            return
        if entry.source_kind == "startup_folder":
            self._set_startup_folder_entry(entry, enabled)

    def _set_registry_startup_entry(self, entry: StartupEntry, enabled: bool) -> None:
        active_path = entry.registry_path or self._active_registry_path(entry.scope)
        disabled_path = self._disabled_registry_path(entry.scope)
        if enabled:
            value = self.registry_get(disabled_path, entry.value_name)
            if value is not None:
                self.registry_set(active_path, entry.value_name, value, "REG_SZ")
                self.registry_delete(disabled_path, entry.value_name)
            self._clear_startup_approved(entry)
            return
        value = self.registry_get(active_path, entry.value_name)
        if value is None:
            return
        self.registry_set(disabled_path, entry.value_name, value, "REG_SZ")
        self.registry_delete(active_path, entry.value_name)

    def _set_startup_folder_entry(self, entry: StartupEntry, enabled: bool) -> None:
        if enabled:
            metadata_path = self._disabled_startup_metadata_path(entry.scope, entry.original_path)
            if metadata_path.exists():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                source = Path(metadata["disabled_path"])
                target = Path(metadata["original_path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.exists():
                    shutil.move(str(source), str(target))
                metadata_path.unlink(missing_ok=True)
            self._clear_startup_approved(entry)
            return
        source = Path(entry.original_path or entry.file_path)
        if not source.exists():
            return
        destination_dir = self.disabled_startup_dir / entry.scope
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{self._startup_path_token(source)}{source.suffix}"
        shutil.move(str(source), str(destination))
        metadata = {
            "scope": entry.scope,
            "name": entry.name,
            "location": entry.location,
            "original_path": str(source),
            "disabled_path": str(destination),
        }
        self._disabled_startup_metadata_path(entry.scope, str(source)).write_text(
            json.dumps(metadata, indent=2),
            encoding="utf-8",
        )

    def run_command(self, command: list[str], description: str = "") -> None:
        self._run_hidden(command, check=False)

    def detect_nvidia_inspector(self, base_dir: Path | str | None = None) -> Path | None:
        return self._cached_probe(
            ("detect_nvidia_inspector", str(base_dir) if base_dir else ""),
            lambda: self._detect_nvidia_inspector_uncached(base_dir),
        )

    def _detect_nvidia_inspector_uncached(self, base_dir: Path | str | None = None) -> Path | None:
        detected = self.detect_nvidia_inspector_known_locations(base_dir)
        if detected:
            return detected
        return None

    def detect_nvidia_profile_inspector_known_locations(self, base_dir: Path | str | None = None) -> Path | None:
        return self._cached_probe(
            ("detect_nvidia_profile_inspector_known_locations", str(base_dir) if base_dir else ""),
            lambda: self._detect_nvidia_profile_inspector_known_locations_uncached(base_dir),
        )

    def _detect_nvidia_profile_inspector_known_locations_uncached(
        self,
        base_dir: Path | str | None = None,
    ) -> Path | None:
        override = self.dependency_overrides.get("nvidiaProfileInspector.exe")
        if override and override.exists():
            return override
        roots: list[Path] = []
        if base_dir:
            roots.append(Path(base_dir))
        roots.append(self.workspace_root)
        candidates = [
            self.tools_root / "nvidiaProfileInspector.exe",
            self.profile_inspector_dir / "nvidiaProfileInspector.exe",
        ]
        for root in roots:
            candidates.extend(
                [
                    root / "nvidiaProfileInspector.exe",
                    root / "tools" / "nvidiaProfileInspector.exe",
                    root / "NVIDIA Profile Inspector" / "nvidiaProfileInspector.exe",
                    root / "tools" / "NVIDIA Profile Inspector" / "nvidiaProfileInspector.exe",
                    root / "bin" / "nvidiaProfileInspector.exe",
                ]
            )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def download_nvidia_profile_inspector(self) -> DependencyInstallResult:
        api_url = "https://api.github.com/repos/Orbmu2k/nvidiaProfileInspector/releases"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Tweakify/0.1",
        }
        try:
            request = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(request) as response:
                releases = json.loads(response.read().decode("utf-8"))
            if not isinstance(releases, list):
                raise ValueError("Unexpected release payload.")
            asset_url = None
            asset_name = ""
            for release in releases:
                assets = release.get("assets", [])
                for asset in assets:
                    name = str(asset.get("name", ""))
                    if name.lower().endswith(".zip"):
                        asset_url = asset.get("browser_download_url")
                        asset_name = name
                        break
                if asset_url:
                    break
            if not asset_url:
                raise FileNotFoundError("No downloadable archive was found in the release feed.")

            archive_request = urllib.request.Request(str(asset_url), headers=headers)
            with urllib.request.urlopen(archive_request) as response:
                archive_bytes = response.read()

            if self.profile_inspector_dir.exists():
                shutil.rmtree(self.profile_inspector_dir)
            self.profile_inspector_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                archive.extractall(self.profile_inspector_dir)

            exe_path = next(self.profile_inspector_dir.rglob("nvidiaProfileInspector.exe"), None)
            if exe_path is None:
                raise FileNotFoundError("The downloaded archive did not contain nvidiaProfileInspector.exe.")
            return DependencyInstallResult(
                dependency_name="NVIDIA Profile Inspector",
                success=True,
                message=f"Downloaded {asset_name} into the managed tools folder.",
                installed_path=str(exe_path),
            )
        except Exception as exc:
            return DependencyInstallResult(
                dependency_name="NVIDIA Profile Inspector",
                success=False,
                message=str(exc),
                installed_path=None,
            )

    def detect_nvidia_inspector_known_locations(self, base_dir: Path | str | None = None) -> Path | None:
        return self._cached_probe(
            ("detect_nvidia_inspector_known_locations", str(base_dir) if base_dir else ""),
            lambda: self._detect_nvidia_inspector_known_locations_uncached(base_dir),
        )

    def _detect_nvidia_inspector_known_locations_uncached(self, base_dir: Path | str | None = None) -> Path | None:
        override = self.dependency_overrides.get("nvidiaInspector.exe")
        if override and override.exists():
            return override
        roots: list[Path] = []
        if base_dir:
            roots.append(Path(base_dir))
        roots.append(self.workspace_root)
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        candidates = [
            self.tools_root / "nvidiaInspector.exe",
            local_app_data / "Tweakify" / "tools" / "NVIDIA Inspector" / "nvidiaInspector.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nvidiaInspector" / "nvidiaInspector.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "nvidiaInspector" / "nvidiaInspector.exe",
        ]
        for root in roots:
            candidates.extend(
                [
                    root / "nvidiaInspector.exe",
                    root / "tools" / "nvidiaInspector.exe",
                    root / "nvidiaInspector" / "nvidiaInspector.exe",
                    root / "tools" / "NVIDIA Inspector" / "nvidiaInspector.exe",
                    root / "bin" / "nvidiaInspector.exe",
                ]
            )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def invoke_nvidia(self, args: list[str]) -> None:
        exe = self.detect_nvidia_inspector()
        if not exe:
            raise FileNotFoundError("nvidiaInspector.exe is unavailable")
        subprocess.run([str(exe), *args], check=False)

    def create_restore_point(self, description: str) -> bool:
        system_drive = os.environ.get("SystemDrive", "C:")
        command = (
            "Enable-ComputerRestore -Drive "
            f"'{system_drive}'; "
            f"Checkpoint-Computer -Description '{description}' -RestorePointType 'MODIFY_SETTINGS'"
        )
        result = self._run_hidden(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    def open_task_manager(self) -> None:
        subprocess.run(["taskmgr.exe"], check=False)

    def open_external_url(self, url: str) -> None:
        try:
            os.startfile(url)  # type: ignore[attr-defined]
        except AttributeError:
            self._run_hidden(["cmd", "/c", "start", "", url], check=False)

    def net_adapter_feature_get(self, feature: str) -> bool | None:
        return self._cached_probe(("net_adapter_feature_get", feature), lambda: self._net_adapter_feature_get_uncached(feature))

    def _net_adapter_feature_get_uncached(self, feature: str) -> bool | None:
        if feature != "lso":
            return None
        script = (
            "$items = Get-NetAdapterLso -Name * -ErrorAction SilentlyContinue | "
            "Select-Object -Property IPv4Enabled,IPv6Enabled | ConvertTo-Json -Compress"
        )
        output = self._run_hidden(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if not output:
            return None
        return "true" in output.lower()

    def net_adapter_feature_set(self, feature: str, enabled: bool) -> None:
        if feature != "lso":
            return
        command = "Enable-NetAdapterLso" if enabled else "Disable-NetAdapterLso"
        script = f"{command} -Name * -IPv4 -IPv6 -Confirm:$false -ErrorAction SilentlyContinue | Out-Null"
        self._run_hidden(["powershell", "-NoProfile", "-Command", script], check=False)

    def is_admin(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def top_cpu_users(self) -> list[str]:
        users = self._cached_probe(("top_cpu_users",), self._top_cpu_users_uncached)
        return list(users)

    def _top_cpu_users_uncached(self) -> list[str]:
        output = self._run_hidden(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process | Sort-Object CPU -Descending | Select-Object -First 3 -ExpandProperty ProcessName",
            ],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        processes = [line.strip() for line in output.splitlines() if line.strip()]
        return processes or ["Unavailable"]

    def memory_pressure(self) -> str:
        return self._cached_probe(("memory_pressure",), self._memory_pressure_uncached)

    def _memory_pressure_uncached(self) -> str:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return f"{status.dwMemoryLoad}%"

    def system_drive_type(self) -> str:
        drive = os.environ.get("SystemDrive", "C:")
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\")
        return {
            2: "Removable",
            3: "SSD/HDD",
            4: "Network",
            5: "CD-ROM",
            6: "RAM Disk",
        }.get(drive_type, "Unknown")

    def bluetooth_device_count(self) -> int:
        return self._cached_probe(("bluetooth_device_count",), self._bluetooth_device_count_uncached)

    def _bluetooth_device_count_uncached(self) -> int:
        output = self._run_hidden(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-PnpDevice -Class Bluetooth -Status OK -ErrorAction SilentlyContinue | Measure-Object).Count",
            ],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        try:
            return int(output)
        except ValueError:
            return 0

    def _read_cim_property(self, expression: str) -> str | None:
        return self._cached_probe(("read_cim_property", expression), lambda: self._read_cim_property_uncached(expression))

    def _read_cim_property_uncached(self, expression: str) -> str | None:
        output = self._run_hidden(
            ["powershell", "-NoProfile", "-Command", expression],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        return output or None

    def _active_registry_path(self, scope: str) -> str:
        return (
            r"HKLM\Software\Microsoft\Windows\CurrentVersion\Run"
            if scope == "machine"
            else r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
        )

    def _disabled_registry_path(self, scope: str) -> str:
        return (
            r"HKLM\Software\Tweakify\DisabledStartup\Run"
            if scope == "machine"
            else r"HKCU\Software\Tweakify\DisabledStartup\Run"
        )

    def _startup_approved_registry_path(self, scope: str) -> str:
        return (
            r"HKLM\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
            if scope == "machine"
            else r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
        )

    def _startup_approved_folder_path(self, scope: str) -> str:
        return (
            r"HKLM\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
            if scope == "machine"
            else r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
        )

    def _startup_status_source(self, approval_value: Any) -> str:
        if isinstance(approval_value, (bytes, bytearray)) and approval_value:
            return "windows_disabled" if approval_value[0] % 2 == 1 else "active"
        return "active"

    def _clear_startup_approved(self, entry: StartupEntry) -> None:
        if entry.source_kind == "registry":
            path = self._startup_approved_registry_path(entry.scope)
            name = entry.value_name
        else:
            path = self._startup_approved_folder_path(entry.scope)
            name = Path(entry.original_path or entry.file_path).name
        if not name:
            return
        self.registry_delete(path, name)

    def _startup_registry_id(self, scope: str, path: str, name: str) -> str:
        return f"registry:{scope}:{path}:{name}"

    def _startup_folder_id(self, scope: str, original_path: str) -> str:
        return f"startup-folder:{scope}:{original_path}"

    def _startup_path_token(self, path: Path) -> str:
        return hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:16]

    def _disabled_startup_metadata_path(self, scope: str, original_path: str) -> Path:
        folder = self.disabled_startup_dir / scope
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{self._startup_path_token(Path(original_path))}.json"

    def _disabled_startup_metadata_paths(self) -> list[Path]:
        if not self.disabled_startup_dir.exists():
            return []
        return sorted(self.disabled_startup_dir.glob("*/*.json"))

    def _split_task_name(self, full_name: str) -> tuple[str, str]:
        normalized = full_name.replace("/", "\\")
        task_name = normalized.rsplit("\\", 1)[-1]
        task_path = normalized[: -len(task_name)]
        if not task_path.endswith("\\"):
            task_path += "\\"
        if not task_path.startswith("\\"):
            task_path = "\\" + task_path
        return task_path, task_name

    def _iter_registry_subkeys(self, hive, root_subkey: str):
        import winreg

        try:
            with winreg.OpenKey(hive, root_subkey) as key:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, index)
                    except OSError as exc:
                        if getattr(exc, "winerror", None) == 259:
                            break
                        raise
                    index += 1
                    yield subkey_name
        except FileNotFoundError:
            return

    def _split_hive(self, path: str):
        import winreg

        normalized = path.replace("/", "\\")
        hive_name, subkey = normalized.split("\\", 1)
        mapping = {
            "HKLM": winreg.HKEY_LOCAL_MACHINE,
            "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
            "HKCU": winreg.HKEY_CURRENT_USER,
            "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
            "HKCR": winreg.HKEY_CLASSES_ROOT,
            "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
        }
        return mapping[hive_name], subkey

    def _devmode(self):
        from ctypes import wintypes

        class DEVMODEW(ctypes.Structure):
            _fields_ = [
                ("dmDeviceName", wintypes.WCHAR * 32),
                ("dmSpecVersion", wintypes.WORD),
                ("dmDriverVersion", wintypes.WORD),
                ("dmSize", wintypes.WORD),
                ("dmDriverExtra", wintypes.WORD),
                ("dmFields", wintypes.DWORD),
                ("dmOrientation", ctypes.c_short),
                ("dmPaperSize", ctypes.c_short),
                ("dmPaperLength", ctypes.c_short),
                ("dmPaperWidth", ctypes.c_short),
                ("dmScale", ctypes.c_short),
                ("dmCopies", ctypes.c_short),
                ("dmDefaultSource", ctypes.c_short),
                ("dmPrintQuality", ctypes.c_short),
                ("dmColor", ctypes.c_short),
                ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short),
                ("dmTTOption", ctypes.c_short),
                ("dmCollate", ctypes.c_short),
                ("dmFormName", wintypes.WCHAR * 32),
                ("dmLogPixels", wintypes.WORD),
                ("dmBitsPerPel", wintypes.DWORD),
                ("dmPelsWidth", wintypes.DWORD),
                ("dmPelsHeight", wintypes.DWORD),
                ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD),
                ("dmICMMethod", wintypes.DWORD),
                ("dmICMIntent", wintypes.DWORD),
                ("dmMediaType", wintypes.DWORD),
                ("dmDitherType", wintypes.DWORD),
                ("dmReserved1", wintypes.DWORD),
                ("dmReserved2", wintypes.DWORD),
                ("dmPanningWidth", wintypes.DWORD),
                ("dmPanningHeight", wintypes.DWORD),
            ]

        devmode = DEVMODEW()
        devmode.dmSize = ctypes.sizeof(DEVMODEW)
        return devmode
