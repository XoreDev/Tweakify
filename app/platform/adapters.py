from __future__ import annotations

import contextvars
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
import threading
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.domain.models import DependencyInstallResult, MachineContext, SnapshotWriter, StartupEntry
from app.platform.processes import hidden_process_kwargs


POWER_PLAN_GUIDS = {
    "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
    "high performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
    "power saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
    "ultimate performance": "e9a42b02-d5df-448d-aa00-03f14749eb61",
}
DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
ERROR_SERVICE_ALREADY_RUNNING = 1056
ERROR_SERVICE_NOT_ACTIVE = 1062
ERROR_SERVICE_DOES_NOT_EXIST = 1060


def ps_quote(value: str) -> str:
    """Quote a value as a PowerShell single-quoted string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def _folder_size(path: Path, limit_files: int = 200_000) -> int:
    total = 0
    seen = 0
    try:
        if path.is_file():
            return path.stat().st_size
        for root, _dirs, files in os.walk(path, onerror=lambda _exc: None):
            for name in files:
                seen += 1
                if seen > limit_files:
                    return total
                try:
                    total += os.lstat(os.path.join(root, name)).st_size
                except OSError:
                    continue
    except OSError:
        return total
    return total


_PROBE_SESSION: contextvars.ContextVar["_ProbeSession | None"] = contextvars.ContextVar("tweakify_probe_session", default=None)


class _ProbeSession:
    def __init__(self, owner: object) -> None:
        self.owner = owner
        self.values: dict[tuple[object, ...], Any] = {}
        self.lock = threading.Lock()
        self.key_locks: dict[tuple[object, ...], threading.Lock] = {}


class ProbeCacheMixin:
    """Memoize read-only probes for the duration of a `probe_session()`.

    The session lives in a ContextVar, not on the facade, so it only covers the
    code that opened it (and worker threads started through `bind_probe_session`).
    An Apply running on another thread while a background scan is open always
    reads live values. A per-key lock lets concurrent workers share one
    subprocess for the same value instead of each spawning their own.
    """

    @contextmanager
    def probe_session(self):
        current = _PROBE_SESSION.get()
        if current is not None and current.owner is self:
            yield
            return
        token = _PROBE_SESSION.set(_ProbeSession(self))
        try:
            yield
        finally:
            _PROBE_SESSION.reset(token)

    def bind_probe_session(self, fn):
        """Wrap `fn` so it runs inside the caller's probe session on a worker thread."""
        session = _PROBE_SESSION.get()

        def run(*args, **kwargs):
            token = _PROBE_SESSION.set(session)
            try:
                return fn(*args, **kwargs)
            finally:
                _PROBE_SESSION.reset(token)

        return run

    def _cached_probe(self, key: tuple[object, ...], loader):
        session = _PROBE_SESSION.get()
        if session is None or session.owner is not self:
            return loader()
        with session.lock:
            if key in session.values:
                return session.values[key]
            key_lock = session.key_locks.setdefault(key, threading.Lock())
        with key_lock:
            with session.lock:
                if key in session.values:
                    return session.values[key]
            value = loader()
            with session.lock:
                session.values[key] = value
            return value


class InMemoryPlatformFacade(ProbeCacheMixin):
    def __init__(self, is_admin: bool = False) -> None:
        self.is_admin = is_admin
        self.registry: dict[tuple[str, str], Any] = {}
        self.registry_types: dict[tuple[str, str], str] = {}
        self.services: dict[str, dict[str, Any]] = {
            "XblAuthManager": {"start_mode": "manual", "running": True},
            "XblGameSave": {"start_mode": "manual", "running": True},
            "bthserv": {"start_mode": "manual", "running": True},
            "BITS": {"start_mode": "auto", "running": True},
            "DiagTrack": {"start_mode": "auto", "running": True},
            "SysMain": {"start_mode": "auto", "running": True},
            "WSearch": {"start_mode": "delayed-auto", "running": True},
            "Spooler": {"start_mode": "auto", "running": True},
            "Fax": {"start_mode": "manual", "running": False},
            "RemoteRegistry": {"start_mode": "disabled", "running": False},
            "MapsBroker": {"start_mode": "delayed-auto", "running": False},
            "WerSvc": {"start_mode": "manual", "running": False},
            "dmwappushservice": {"start_mode": "manual", "running": False},
            "RetailDemo": {"start_mode": "manual", "running": False},
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
        self.power_settings: dict[tuple[str, str], dict[str, int | None]] = {}
        self.hibernate_enabled: bool | None = True
        self.mmagent: dict[str, bool] = {"MemoryCompression": True}
        self.dns_servers: dict[str, list[str]] = {"Ethernet": []}
        self.gpu_vendors: tuple[str, ...] = ("NVIDIA",)
        self.is_laptop = False
        self.nvidia_profile_imports: list[dict[int, int]] = []
        self.command_return_codes: dict[str, int] = {}
        self.cleanup_sizes: dict[str, int] = {}
        self.restore_point_result = True
        self.net_adapter_properties: dict[str, dict[str, str | None]] = {"Ethernet": {"*EEE": "1", "*InterruptModeration": "1"}}
        self.bcd_values: dict[str, str] = {}

    def snapshot_writer(self) -> SnapshotWriter:
        return SnapshotWriter()

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
                nvidia_profile_inspector_path=str(self.dependency_overrides.get("nvidiaProfileInspector.exe") or self.profile_inspector_path)
                if (self.dependency_overrides.get("nvidiaProfileInspector.exe") or self.profile_inspector_path)
                else None,
                gpu_vendors=self.gpu_vendors,
                is_laptop=self.is_laptop,
            ),
        )

    def diagnostic_probe(self, startup_count: int | None = None) -> dict[str, Any]:
        data = self.diagnostics.copy()
        data["startup_count"] = startup_count if startup_count is not None else self.startup_inventory()["count"]
        return data

    def registry_get(self, path: str, name: str) -> Any:
        return self.registry.get((path, name))

    def registry_get_typed(self, path: str, name: str) -> tuple[Any, str | None]:
        key = (path, name)
        if key not in self.registry:
            return None, None
        return self.registry[key], self.registry_types.get(key, "REG_DWORD")

    def registry_set(self, path: str, name: str, value: Any, value_type: str = "REG_DWORD") -> None:
        self.registry[(path, name)] = value
        self.registry_types[(path, name)] = value_type

    def registry_delete(self, path: str, name: str) -> None:
        self.registry.pop((path, name), None)
        self.registry_types.pop((path, name), None)

    def service_get(self, name: str) -> dict[str, Any]:
        service = self._cached_probe(
            ("service_get", name),
            lambda: dict(self.services.get(name, {"start_mode": "missing", "running": False})),
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

    def scheduled_task_register(self, name: str, arguments: list[str]) -> None:
        self.scheduled_tasks[name] = {"name": name, "enabled": True, "arguments": list(arguments)}
        self.command_log.append(f"schtasks-create:{name}")

    def scheduled_task_delete(self, name: str) -> None:
        self.scheduled_tasks.pop(name, None)
        self.command_log.append(f"schtasks-delete:{name}")

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

    def set_interface_value_for(self, adapter: str, name: str, value: Any) -> None:
        self.interface_values.setdefault(adapter, {})[name] = value

    def clear_interface_value_for(self, adapter: str, name: str) -> None:
        self.interface_values.get(adapter, {}).pop(name, None)

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

    def power_plan_matches(self, state: dict[str, Any], plan: str) -> bool:
        return str(state.get("name", "")).lower() == plan.lower()

    def power_setting_get(self, subgroup: str, setting: str) -> dict[str, int | None]:
        return dict(self.power_settings.get((subgroup, setting), {"ac": 1, "dc": 1}))

    def power_setting_set(self, subgroup: str, setting: str, ac: int | None, dc: int | None) -> None:
        current = self.power_settings.setdefault((subgroup, setting), {"ac": 1, "dc": 1})
        if ac is not None:
            current["ac"] = ac
        if dc is not None:
            current["dc"] = dc
        self.command_log.append(f"powercfg:{subgroup}/{setting}={ac},{dc}")

    def hibernation_enabled(self) -> bool | None:
        return self.hibernate_enabled

    def hibernation_set(self, enabled: bool) -> None:
        self.hibernate_enabled = enabled
        self.command_log.append(f"hibernate:{enabled}")

    def mmagent_get(self, feature: str) -> bool | None:
        return self.mmagent.get(feature)

    def mmagent_set(self, feature: str, enabled: bool) -> None:
        self.mmagent[feature] = enabled
        self.command_log.append(f"mmagent:{feature}={enabled}")

    def dns_get_servers(self) -> dict[str, list[str]]:
        return {alias: list(servers) for alias, servers in self.dns_servers.items()}

    def dns_set_servers(self, alias: str, servers: list[str] | None) -> None:
        self.dns_servers[alias] = list(servers or [])
        self.command_log.append(f"dns:{alias}={','.join(servers or []) or 'dhcp'}")

    def nvidia_profile_apply(self, settings: dict[int, int]) -> None:
        if not (self.dependency_overrides.get("nvidiaProfileInspector.exe") or self.profile_inspector_path):
            raise FileNotFoundError("nvidiaProfileInspector.exe is unavailable")
        self.nvidia_profile_imports.append(dict(settings))
        self.command_log.append("nvidia-profile:" + ",".join(f"{key}={value}" for key, value in settings.items()))

    def cleanup_estimate(self, targets: dict[str, list[str]]) -> dict[str, int]:
        return {target_id: int(self.cleanup_sizes.get(target_id, 0)) for target_id in targets}

    def net_adapter_property_get(self, keyword: str) -> dict[str, str | None]:
        return {adapter: values.get(keyword) for adapter, values in self.net_adapter_properties.items() if keyword in values}

    def net_adapter_property_set(self, adapter: str, keyword: str, value: str) -> None:
        self.net_adapter_properties.setdefault(adapter, {})[keyword] = value
        self.command_log.append(f"nic:{adapter}:{keyword}={value}")

    def bcd_get(self, name: str) -> str | None:
        return self.bcd_values.get(name)

    def bcd_set(self, name: str, value: str | None) -> None:
        if value is None:
            self.bcd_values.pop(name, None)
        else:
            self.bcd_values[name] = value
        self.command_log.append(f"bcd:{name}={value}")

    def network_latency(self, hosts: list[str]) -> dict[str, float | None]:
        return {host: 12.0 for host in hosts}

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

    def run_command(self, command: list[str], description: str = "", timeout: int | None = None) -> int:
        self.command_log.append(" ".join(command) if not description else f"{description}: {' '.join(command)}")
        return self.command_return_codes.get(command[0], 0)

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
        return self.restore_point_result

    def open_task_manager(self) -> None:
        self.command_log.append("taskmgr")

    def create_live_sampler(self):
        from app.platform.live import SyntheticLiveSampler

        return SyntheticLiveSampler()

    def purge_standby_list(self) -> bool:
        self.command_log.append("purge-standby-list")
        return self.is_admin

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


class WindowsPlatformFacade(ProbeCacheMixin):
    supports_elevated_helper = True
    # Most probes wait on a PowerShell/powercfg/schtasks subprocess, so a small
    # thread pool overlaps them (14 s -> ~3 s on a typical machine).
    probe_workers = 8

    def __init__(
        self,
        workspace_root: Path | str | None = None,
        data_root: Path | str | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root or Path(__file__).resolve().parents[2])
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
        profile_path = self.detect_nvidia_profile_inspector_known_locations()
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
            nvidia_profile_inspector_path=str(profile_path) if profile_path else None,
            gpu_vendors=self.gpu_vendors(),
            is_laptop=self.is_laptop(),
        )

    def gpu_vendors(self) -> tuple[str, ...]:
        return self._cached_probe(("gpu_vendors",), self._gpu_vendors_uncached)

    def _gpu_vendors_uncached(self) -> tuple[str, ...]:
        names = self._read_cim_property("(Get-CimInstance Win32_VideoController).Name") or ""
        vendors: list[str] = []
        for line in names.splitlines():
            lowered = line.lower()
            for token, vendor in (("nvidia", "NVIDIA"), ("geforce", "NVIDIA"), ("radeon", "AMD"), ("amd", "AMD"), ("intel", "Intel")):
                if token in lowered and vendor not in vendors:
                    vendors.append(vendor)
        return tuple(vendors)

    def is_laptop(self) -> bool:
        return self._cached_probe(("is_laptop",), self._is_laptop_uncached)

    def _is_laptop_uncached(self) -> bool:
        output = self._read_cim_property("(Get-CimInstance Win32_SystemEnclosure).ChassisTypes") or ""
        # SMBIOS chassis types for portables: laptop, notebook, sub-notebook, tablet, convertible, detachable.
        portable = {"8", "9", "10", "14", "30", "31", "32"}
        return any(token.strip() in portable for token in output.split())

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
            "disk_free_bytes": free,
            "drive_type": self.system_drive_type(),
            "pending_updates": pending_updates,
            "vbs_status": vbs_status,
            "memory_integrity": memory_integrity,
            "indexing_state": self.service_get("WSearch")["start_mode"].title(),
            "delivery_optimization": self.service_get("DoSvc")["start_mode"].title(),
            "uptime_hours": round(ctypes.windll.kernel32.GetTickCount64() / 3_600_000, 1),
            "power_plan": self.power_get_active_plan().get("name", "Unknown"),
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

    def registry_get_typed(self, path: str, name: str) -> tuple[Any, str | None]:
        import winreg

        hive, subkey = self._split_hive(path)
        names = {
            winreg.REG_SZ: "REG_SZ",
            winreg.REG_EXPAND_SZ: "REG_EXPAND_SZ",
            winreg.REG_DWORD: "REG_DWORD",
            winreg.REG_QWORD: "REG_QWORD",
            winreg.REG_MULTI_SZ: "REG_MULTI_SZ",
            winreg.REG_BINARY: "REG_BINARY",
        }
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, value_type = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return None, None
        if isinstance(value, bytes):
            # bytes are not JSON-serialisable; snapshots store them as hex.
            return value.hex(), "REG_BINARY_HEX"
        return value, names.get(value_type, "REG_SZ")

    def registry_set(self, path: str, name: str, value: Any, value_type: str = "REG_DWORD") -> None:
        import winreg

        hive, subkey = self._split_hive(path)
        if value_type == "REG_BINARY_HEX":
            value_type, value = "REG_BINARY", bytes.fromhex(str(value))
        reg_type = getattr(winreg, value_type, winreg.REG_DWORD)
        if reg_type in (winreg.REG_DWORD, winreg.REG_QWORD) and not isinstance(value, int):
            value = int(value)
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
        # PermissionError and other OSErrors propagate: a delete that silently
        # fails would be reported to the user as an applied change.

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
        if qc.returncode == ERROR_SERVICE_DOES_NOT_EXIST:
            return {"start_mode": "missing", "running": False}
        start_mode = "unknown"
        for line in qc.stdout.splitlines():
            if "START_TYPE" in line:
                if "DISABLED" in line:
                    start_mode = "disabled"
                elif "DEMAND_START" in line:
                    start_mode = "manual"
                elif "AUTO_START" in line:
                    start_mode = "delayed-auto" if "DELAYED" in line else "auto"
                elif "BOOT_START" in line:
                    start_mode = "boot"
                elif "SYSTEM_START" in line:
                    start_mode = "system"
                break
        running = "RUNNING" in query.stdout
        return {"start_mode": start_mode, "running": running}

    def service_set(self, name: str, start_mode: str) -> None:
        mapping = {
            "manual": "demand",
            "auto": "auto",
            "delayed-auto": "delayed-auto",
            "disabled": "disabled",
            "boot": "boot",
            "system": "system",
        }
        # sc.exe needs "start=" and the mode as two separate arguments. Passing
        # "start= demand" as one argument makes sc reject the call, so no service
        # change was ever applied before this fix.
        result = self._run_hidden(
            ["sc", "config", name, "start=", mapping[start_mode]],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"sc config {name} failed ({result.returncode}): {self._tail(result)}")

    def service_stop(self, name: str) -> None:
        result = self._run_hidden(["sc", "stop", name], capture_output=True, text=True, check=False)
        if result.returncode not in (0, ERROR_SERVICE_NOT_ACTIVE):
            raise RuntimeError(f"sc stop {name} failed ({result.returncode}): {self._tail(result)}")

    def service_start(self, name: str) -> None:
        result = self._run_hidden(["sc", "start", name], capture_output=True, text=True, check=False)
        if result.returncode not in (0, ERROR_SERVICE_ALREADY_RUNNING):
            raise RuntimeError(f"sc start {name} failed ({result.returncode}): {self._tail(result)}")

    @staticmethod
    def _tail(result) -> str:
        text = ((getattr(result, "stdout", "") or "") + " " + (getattr(result, "stderr", "") or "")).strip()
        return " ".join(text.split())[-240:] or "no output"

    def scheduled_task_get(self, name: str) -> dict[str, Any] | None:
        task = self._cached_probe(("scheduled_task_get", name), lambda: self._scheduled_task_get_uncached(name))
        return dict(task) if task else None

    def _scheduled_task_get_uncached(self, name: str) -> dict[str, Any] | None:
        task_path, task_name = self._split_task_name(name)
        script = (
            f"$task = Get-ScheduledTask -TaskPath {ps_quote(task_path)} -TaskName {ps_quote(task_name)} -ErrorAction SilentlyContinue; "
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
        script = f"{command} -TaskPath {ps_quote(task_path)} -TaskName {ps_quote(task_name)} -ErrorAction Stop | Out-Null"
        result = self._run_hidden(
            ["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise RuntimeError(f"{command} {name} failed: {self._tail(result)}")

    def scheduled_task_register(self, name: str, arguments: list[str]) -> None:
        """Register a weekly task that runs this Tweakify install headless with `arguments`."""
        interpreter = Path(sys.executable)
        windowless = interpreter.with_name("pythonw.exe")
        if windowless.exists():
            interpreter = windowless
        launcher = self.workspace_root / "Tweakify.py"
        task_command = subprocess.list2cmdline([str(interpreter), str(launcher), *arguments])
        if len(task_command) > 261:
            raise RuntimeError("The Tweakify install path is too long for a scheduled task command.")
        result = self._run_hidden(
            ["schtasks", "/Create", "/TN", name, "/TR", task_command, "/SC", "WEEKLY", "/D", "SUN",
             "/ST", "12:00", "/RL", "HIGHEST", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"schtasks /Create {name} failed: {self._tail(result)}")

    def scheduled_task_delete(self, name: str) -> None:
        if self._scheduled_task_get_uncached(name) is None:
            return
        result = self._run_hidden(["schtasks", "/Delete", "/TN", name, "/F"], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"schtasks /Delete {name} failed: {self._tail(result)}")

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

    def set_interface_value_for(self, adapter: str, name: str, value: Any) -> None:
        self.registry_set(
            rf"HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\{adapter}", name, value, "REG_DWORD"
        )

    def clear_interface_value_for(self, adapter: str, name: str) -> None:
        self.registry_delete(rf"HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\{adapter}", name)

    def get_tcp_global(self, key: str) -> str | None:
        return self._cached_probe(("get_tcp_global", key), lambda: self._get_tcp_global_uncached(key))

    def _get_tcp_global_uncached(self, key: str) -> str | None:
        return self._tcp_settings().get(key)

    def _tcp_settings(self) -> dict[str, str]:
        return self._cached_probe(("tcp_settings",), self._tcp_settings_uncached)

    def _tcp_settings_uncached(self) -> dict[str, str]:
        # The NetTCPIP cmdlets return enum names, which are not localized. netsh
        # output is, so matching English labels failed on non-English Windows.
        script = (
            "$t = Get-NetTCPSetting -SettingName Internet -ErrorAction SilentlyContinue; "
            "$o = Get-NetOffloadGlobalSetting -ErrorAction SilentlyContinue; "
            "[pscustomobject]@{ autotuninglevel = \"$($t.AutoTuningLevelLocal)\"; "
            "heuristics = \"$($t.ScalingHeuristics)\"; ecncapability = \"$($t.EcnCapability)\"; "
            "rss = \"$($o.ReceiveSideScaling)\" } | ConvertTo-Json -Compress"
        )
        output = self._run_hidden(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        try:
            payload = json.loads(output) if output else {}
        except ValueError:
            payload = {}
        values = {key: str(value).strip().lower() for key, value in payload.items() if str(value).strip()}
        # Normalise PowerShell enum names to the netsh vocabulary the actions use.
        aliases = {"highlyrestricted": "highlyrestricted", "normal": "normal", "disabled": "disabled"}
        if "autotuninglevel" in values:
            values["autotuninglevel"] = aliases.get(values["autotuninglevel"], values["autotuninglevel"])
        return values

    def set_tcp_global(self, key: str, value: str) -> None:
        if key == "heuristics":
            command = ["netsh", "int", "tcp", "set", "heuristics", value]
        elif key == "template":
            command = ["netsh", "int", "tcp", "set", "supplemental", f"template={value}"]
        else:
            command = ["netsh", "int", "tcp", "set", "global", f"{key}={value}"]
        result = self._run_hidden(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"{' '.join(command)} failed: {self._tail(result)}")

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

    def _power_schemes(self) -> list[dict[str, str]]:
        output = self._run_hidden(["powercfg", "/L"], capture_output=True, text=True, check=False).stdout
        return [
            {"guid": match.group(1).lower(), "name": match.group(2)}
            for match in re.finditer(r"([A-Fa-f0-9]{8}-[A-Fa-f0-9\-]{27})\s+\((.+?)\)", output)
        ]

    def _resolve_power_plan(self, name: str) -> str:
        lowered = name.lower()
        if re.fullmatch(r"[a-f0-9]{8}-[a-f0-9\-]{27}", lowered):
            return lowered
        guid = POWER_PLAN_GUIDS.get(lowered)
        schemes = self._power_schemes()
        if guid and any(scheme["guid"] == guid for scheme in schemes):
            return guid
        if lowered == "ultimate performance":
            # The Ultimate Performance scheme is hidden on most editions. It has
            # to be duplicated from its template before it can be activated.
            for scheme in schemes:
                if "ultimate" in scheme["name"].lower():
                    return scheme["guid"]
            output = self._run_hidden(
                ["powercfg", "-duplicatescheme", POWER_PLAN_GUIDS["ultimate performance"]],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            match = re.search(r"([A-Fa-f0-9]{8}-[A-Fa-f0-9\-]{27})", output)
            if match:
                return match.group(1).lower()
        if guid:
            return guid
        for scheme in schemes:
            if scheme["name"].lower() == lowered:
                return scheme["guid"]
        raise RuntimeError(f"Power plan '{name}' is not available on this machine.")

    def power_set_active_plan(self, name: str) -> None:
        token = self._resolve_power_plan(name)
        result = self._run_hidden(["powercfg", "/S", token], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"powercfg /S {token} failed: {self._tail(result)}")

    def power_plan_matches(self, state: dict[str, Any], plan: str) -> bool:
        guid = str(state.get("guid", "")).lower()
        name = str(state.get("name", "")).lower()
        lowered = plan.lower()
        if lowered == "ultimate performance":
            return guid == POWER_PLAN_GUIDS[lowered] or "ultimate" in name
        return guid == POWER_PLAN_GUIDS.get(lowered) or name == lowered

    def power_setting_get(self, subgroup: str, setting: str) -> dict[str, int | None]:
        output = self._run_hidden(
            ["powercfg", "/QH", "SCHEME_CURRENT", subgroup, setting],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        indexes = re.findall(r":\s*0x([0-9A-Fa-f]{8})\s*$", output, flags=re.MULTILINE)
        # /QH prints min/max/increment lines for ranged settings before the two
        # current-index lines, so the last two hex values are always AC then DC.
        if len(indexes) < 2:
            return {"ac": None, "dc": None}
        return {"ac": int(indexes[-2], 16), "dc": int(indexes[-1], 16)}

    def power_setting_set(self, subgroup: str, setting: str, ac: int | None, dc: int | None) -> None:
        for flag, value in (("/SETACVALUEINDEX", ac), ("/SETDCVALUEINDEX", dc)):
            if value is None:
                continue
            result = self._run_hidden(
                ["powercfg", flag, "SCHEME_CURRENT", subgroup, setting, str(int(value))],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(f"powercfg {flag} {setting} failed: {self._tail(result)}")
        self._run_hidden(["powercfg", "/S", "SCHEME_CURRENT"], check=False)

    def hibernation_enabled(self) -> bool | None:
        value = self.registry_get(r"HKLM\SYSTEM\CurrentControlSet\Control\Power", "HibernateEnabled")
        return None if value is None else bool(value)

    def hibernation_set(self, enabled: bool) -> None:
        result = self._run_hidden(
            ["powercfg", "/hibernate", "on" if enabled else "off"], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise RuntimeError(f"powercfg /hibernate failed: {self._tail(result)}")

    def mmagent_get(self, feature: str) -> bool | None:
        output = self._read_cim_property(f"(Get-MMAgent -ErrorAction SilentlyContinue).{feature}")
        if output is None:
            return None
        return output.strip().lower() == "true"

    def mmagent_set(self, feature: str, enabled: bool) -> None:
        verb = "Enable-MMAgent" if enabled else "Disable-MMAgent"
        result = self._run_hidden(
            ["powershell", "-NoProfile", "-Command", f"{verb} -{feature} -ErrorAction Stop"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"{verb} -{feature} failed: {self._tail(result)}")

    def dns_get_servers(self) -> dict[str, list[str]]:
        return self._cached_probe(("dns_get_servers",), self._dns_get_servers_uncached)

    def _dns_get_servers_uncached(self) -> dict[str, list[str]]:
        script = (
            "$up = Get-NetAdapter -Physical -ErrorAction SilentlyContinue | Where-Object Status -eq 'Up' | "
            "Select-Object -ExpandProperty InterfaceAlias; $out = @{}; foreach ($a in $up) { "
            "$s = Get-DnsClientServerAddress -InterfaceAlias $a -AddressFamily IPv4 -ErrorAction SilentlyContinue; "
            "$static = Get-ItemProperty -Path \"HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces\\$((Get-NetAdapter -InterfaceAlias $a).InterfaceGuid)\" -Name NameServer -ErrorAction SilentlyContinue; "
            "$out[$a] = @(if ($static.NameServer) { $s.ServerAddresses } else { @() }) }; $out | ConvertTo-Json -Compress"
        )
        output = self._run_hidden(
            ["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, check=False
        ).stdout.strip()
        try:
            payload = json.loads(output) if output else {}
        except ValueError:
            return {}
        if not isinstance(payload, dict):
            return {}
        result: dict[str, list[str]] = {}
        for alias, servers in payload.items():
            if isinstance(servers, str):
                servers = [servers]
            result[str(alias)] = [str(item) for item in (servers or [])]
        return result

    def dns_set_servers(self, alias: str, servers: list[str] | None) -> None:
        if servers:
            listed = ",".join(ps_quote(server) for server in servers)
            script = f"Set-DnsClientServerAddress -InterfaceAlias {ps_quote(alias)} -ServerAddresses @({listed}) -ErrorAction Stop"
        else:
            script = f"Set-DnsClientServerAddress -InterfaceAlias {ps_quote(alias)} -ResetServerAddresses -ErrorAction Stop"
        result = self._run_hidden(
            ["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise RuntimeError(f"Setting DNS on {alias} failed: {self._tail(result)}")
        self._run_hidden(["ipconfig", "/flushdns"], capture_output=True, check=False)

    def net_adapter_property_get(self, keyword: str) -> dict[str, str | None]:
        return self._cached_probe(("net_adapter_property_get", keyword), lambda: self._net_adapter_property_get_uncached(keyword))

    def _net_adapter_property_get_uncached(self, keyword: str) -> dict[str, str | None]:
        script = (
            "Get-NetAdapter -Physical -ErrorAction SilentlyContinue | "
            f"Get-NetAdapterAdvancedProperty -RegistryKeyword {ps_quote(keyword)} -ErrorAction SilentlyContinue | "
            "ForEach-Object { [pscustomobject]@{ name = $_.Name; value = [string]($_.RegistryValue | Select-Object -First 1) } } | "
            "ConvertTo-Json -Compress"
        )
        output = self._run_hidden(
            ["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, check=False
        ).stdout.strip()
        try:
            payload = json.loads(output) if output else []
        except ValueError:
            return {}
        if isinstance(payload, dict):
            payload = [payload]
        return {str(item.get("name")): (str(item.get("value")) if item.get("value") not in (None, "") else None) for item in payload}

    def net_adapter_property_set(self, adapter: str, keyword: str, value: str) -> None:
        script = (
            f"Set-NetAdapterAdvancedProperty -Name {ps_quote(adapter)} -RegistryKeyword {ps_quote(keyword)} "
            f"-RegistryValue {ps_quote(value)} -NoRestart:$false -ErrorAction Stop"
        )
        result = self._run_hidden(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"Setting {keyword} on {adapter} failed: {self._tail(result)}")

    def bcd_get(self, name: str) -> str | None:
        return self._cached_probe(("bcd_get", name), lambda: self._bcd_get_uncached(name))

    def _bcd_get_uncached(self, name: str) -> str | None:
        result = self._run_hidden(["bcdedit", "/enum", "{current}"], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError("The boot configuration can only be read with administrator rights.")
        for line in result.stdout.splitlines():
            parts = line.split(None, 1)
            if parts and parts[0].lower() == name.lower():
                return parts[1].strip() if len(parts) > 1 else ""
        return None

    def bcd_set(self, name: str, value: str | None) -> None:
        if value is None:
            if self._bcd_get_uncached(name) is None:
                return
            command = ["bcdedit", "/deletevalue", "{current}", name]
        else:
            command = ["bcdedit", "/set", "{current}", name, value]
        result = self._run_hidden(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"{' '.join(command)} failed: {self._tail(result)}")

    def network_latency(self, hosts: list[str]) -> dict[str, float | None]:
        results: dict[str, float | None] = {}
        for host in hosts:
            output = self._run_hidden(
                ["ping", "-n", "4", "-w", "1000", host], capture_output=True, text=True, check=False
            ).stdout
            times = [float(value) for value in re.findall(r"[=<](\d+)ms", output)]
            results[host] = round(sum(times) / len(times), 1) if times else None
        return results

    def cleanup_estimate(self, targets: dict[str, list[str]]) -> dict[str, int]:
        return {
            target_id: sum(_folder_size(Path(os.path.expandvars(path))) for path in paths)
            for target_id, paths in targets.items()
        }

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
        current = self._devmode()
        if not ctypes.windll.user32.EnumDisplaySettingsW(None, -1, ctypes.byref(current)):
            return None
        index = 0
        highest = None
        while True:
            devmode = self._devmode()
            if not ctypes.windll.user32.EnumDisplaySettingsW(None, index, ctypes.byref(devmode)):
                break
            index += 1
            # Only modes at the current resolution and colour depth count. The
            # highest rate overall is often only offered at a lower resolution.
            if (
                devmode.dmPelsWidth != current.dmPelsWidth
                or devmode.dmPelsHeight != current.dmPelsHeight
                or devmode.dmBitsPerPel != current.dmBitsPerPel
            ):
                continue
            highest = max(highest or 0, int(devmode.dmDisplayFrequency))
        return highest

    def display_set_refresh_rate(self, value: int) -> None:
        devmode = self._devmode()
        ENUM_CURRENT_SETTINGS = -1
        DM_DISPLAYFREQUENCY = 0x00400000
        CDS_UPDATEREGISTRY = 0x00000001
        if not ctypes.windll.user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(devmode)):
            raise RuntimeError("The current display mode could not be read.")
        devmode.dmFields |= DM_DISPLAYFREQUENCY
        devmode.dmDisplayFrequency = int(value)
        # CDS_UPDATEREGISTRY persists the mode; flag 0 reverted it on the next reboot.
        result = ctypes.windll.user32.ChangeDisplaySettingsW(ctypes.byref(devmode), CDS_UPDATEREGISTRY)
        if result != 0:
            raise RuntimeError(f"The display rejected {value}Hz (ChangeDisplaySettings returned {result}).")

    def startup_inventory(self) -> dict[str, Any]:
        items_by_id: dict[str, StartupEntry] = {}
        for path, location, scope, approval_path in [
            (r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run", "Run", "user", None),
            (r"HKLM\Software\Microsoft\Windows\CurrentVersion\Run", "Run (Machine)", "machine", None),
            (
                r"HKLM\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
                "Run (Machine, 32-bit)",
                "machine32",
                r"HKLM\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run32",
            ),
        ]:
            approval_values = self.registry_value_map(approval_path or self._startup_approved_registry_path(scope))
            for name, command in self.registry_value_map(path).items():
                if not name:
                    continue
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
            (r"HKLM\Software\Tweakify\DisabledStartup\Run32", "Run (Machine, 32-bit)", "machine32"),
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
                # desktop.ini is shell metadata, not something that launches at sign-in.
                if item.name.lower() == "desktop.ini" or item.is_dir():
                    continue
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
            value, value_type = self.registry_get_typed(disabled_path, entry.value_name)
            if value is not None:
                self.registry_set(active_path, entry.value_name, value, value_type or "REG_SZ")
                self.registry_delete(disabled_path, entry.value_name)
            self._clear_startup_approved(entry)
            return
        # Keep the original value type. Many Run entries are REG_EXPAND_SZ
        # (%ProgramFiles%\...), and rewriting them as REG_SZ broke them on re-enable.
        value, value_type = self.registry_get_typed(active_path, entry.value_name)
        if value is None:
            return
        self.registry_set(disabled_path, entry.value_name, value, value_type or "REG_SZ")
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

    def run_command(self, command: list[str], description: str = "", timeout: int | None = 1800) -> int:
        executable = command[0]
        if os.path.isabs(executable) and not os.path.exists(executable):
            raise FileNotFoundError(f"{executable} was not found on this machine.")
        try:
            result = self._run_hidden(
                command,
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"{Path(executable).name} did not finish within {timeout} seconds.") from exc
        return result.returncode

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
            with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                releases = json.loads(response.read().decode("utf-8"))
            if not isinstance(releases, list):
                raise ValueError("Unexpected release payload.")
            asset_url = None
            asset_name = ""
            stable = [release for release in releases if not release.get("prerelease") and not release.get("draft")]
            for release in stable or releases:
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

            if not str(asset_url).startswith("https://github.com/"):
                raise ValueError("The release asset is not hosted on github.com; refusing to download it.")
            archive_request = urllib.request.Request(str(asset_url), headers=headers)
            with urllib.request.urlopen(archive_request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                archive_bytes = response.read(MAX_DOWNLOAD_BYTES + 1)
            if len(archive_bytes) > MAX_DOWNLOAD_BYTES:
                raise ValueError("The release archive is larger than expected; refusing to extract it.")

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
        self._run_hidden([str(exe), *args], check=False, timeout=60)

    def nvidia_profile_apply(self, settings: dict[int, int]) -> None:
        """Import DWORD settings into the driver's Base (global) profile."""
        exe = self.detect_nvidia_profile_inspector_known_locations()
        if not exe:
            raise FileNotFoundError("nvidiaProfileInspector.exe is unavailable")
        rows = "".join(
            "<ProfileSetting><SettingNameInfo> </SettingNameInfo>"
            f"<SettingID>{int(setting_id)}</SettingID><SettingValue>{int(value)}</SettingValue>"
            "<ValueType>Dword</ValueType></ProfileSetting>"
            for setting_id, value in settings.items()
        )
        document = (
            '<?xml version="1.0" encoding="utf-16"?>\r\n<ArrayOfProfile><Profile>'
            "<ProfileName>Base Profile</ProfileName><Executeables /><Settings>"
            f"{rows}</Settings></Profile></ArrayOfProfile>"
        )
        cache_dir = self.tweakify_root / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        nip_path = cache_dir / "tweakify-nvidia.nip"
        nip_path.write_text(document, encoding="utf-16")
        try:
            result = self._run_hidden([str(exe), str(nip_path), "-silent"], check=False, timeout=60)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("NVIDIA Profile Inspector did not finish the import within 60 seconds.") from exc
        if result.returncode != 0:
            raise RuntimeError(f"NVIDIA Profile Inspector import failed with code {result.returncode}.")

    def create_restore_point(self, description: str) -> bool:
        system_drive = os.environ.get("SystemDrive", "C:")
        # Windows silently skips a restore point if another was created in the
        # last 24 hours. Lift that limit for this call, then put it back.
        command = (
            "$ErrorActionPreference = 'Stop'; "
            "$key = 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\SystemRestore'; "
            "$old = (Get-ItemProperty -Path $key -Name SystemRestorePointCreationFrequency -ErrorAction SilentlyContinue).SystemRestorePointCreationFrequency; "
            "Set-ItemProperty -Path $key -Name SystemRestorePointCreationFrequency -Value 0 -Type DWord; "
            "try { "
            f"Enable-ComputerRestore -Drive {ps_quote(system_drive + chr(92))}; "
            "$before = @(Get-ComputerRestorePoint -ErrorAction SilentlyContinue).Count; "
            f"Checkpoint-Computer -Description {ps_quote(description[:255])} -RestorePointType 'MODIFY_SETTINGS'; "
            "$after = @(Get-ComputerRestorePoint -ErrorAction SilentlyContinue).Count; "
            "if ($after -le $before) { exit 3 } "
            "} finally { "
            "if ($null -eq $old) { Remove-ItemProperty -Path $key -Name SystemRestorePointCreationFrequency -ErrorAction SilentlyContinue } "
            "else { Set-ItemProperty -Path $key -Name SystemRestorePointCreationFrequency -Value $old -Type DWord } }"
        )
        try:
            result = self._run_hidden(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            return False
        return result.returncode == 0

    def open_task_manager(self) -> None:
        # Popen, not run: run() blocked the GUI thread until Task Manager closed.
        subprocess.Popen(["taskmgr.exe"])

    def create_live_sampler(self):
        from app.platform.live import SyntheticLiveSampler, WindowsLiveSampler

        try:
            return WindowsLiveSampler()
        except (AttributeError, OSError):
            return SyntheticLiveSampler()

    def purge_standby_list(self) -> bool:
        from app.platform.live import purge_standby_list

        return purge_standby_list()

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
        return self._cached_probe(("system_drive_type",), self._system_drive_type_uncached)

    def _system_drive_type_uncached(self) -> str:
        drive = os.environ.get("SystemDrive", "C:")
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\")
        if drive_type == 3:
            letter = drive.rstrip(":\\")[:1] or "C"
            media = self._read_cim_property(
                f"(Get-Partition -DriveLetter {letter} -ErrorAction SilentlyContinue | Get-Disk | Get-PhysicalDisk).MediaType"
            )
            if media and media.strip().upper() in {"SSD", "HDD", "SCM"}:
                return media.strip().upper()
            return "Fixed"
        return {
            2: "Removable",
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
        return {
            "machine": r"HKLM\Software\Microsoft\Windows\CurrentVersion\Run",
            "machine32": r"HKLM\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
        }.get(scope, r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run")

    def _disabled_registry_path(self, scope: str) -> str:
        return {
            "machine": r"HKLM\Software\Tweakify\DisabledStartup\Run",
            "machine32": r"HKLM\Software\Tweakify\DisabledStartup\Run32",
        }.get(scope, r"HKCU\Software\Tweakify\DisabledStartup\Run")

    def _startup_approved_registry_path(self, scope: str) -> str:
        return {
            "machine": r"HKLM\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run",
            "machine32": r"HKLM\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run32",
        }.get(scope, r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run")

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
