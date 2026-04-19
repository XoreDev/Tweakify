import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from app.actions.catalog import build_action_catalog
from app.platform.adapters import InMemoryPlatformFacade, WindowsPlatformFacade
from app.platform.elevation import ElevationManager
from app.platform.processes import hidden_process_kwargs
from tests.conftest import ROOT


def test_registry_backed_action_apply_and_rollback():
    platform = InMemoryPlatformFacade(is_admin=True)
    actions = {action.definition.id: action for action in build_action_catalog(platform)}
    action = actions["disable_telemetry"]

    result = action.apply(True, platform.snapshot_writer())
    assert result.success is True
    assert platform.registry_get(
        r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection",
        "AllowTelemetry",
    ) == 0

    rollback = action.rollback(result.snapshot_entry)
    assert rollback.success is True
    assert platform.registry_get(
        r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection",
        "AllowTelemetry",
    ) is None


def test_system_parameter_action_applies_mouse_precision_and_broadcasts():
    platform = InMemoryPlatformFacade(is_admin=True)
    actions = {action.definition.id: action for action in build_action_catalog(platform)}
    action = actions["disable_enhance_pointer_precision"]

    result = action.apply(True, platform.snapshot_writer())

    assert result.success is True
    assert platform.pointer_precision_enabled is False
    assert "broadcast:mouse" in platform.command_log

    rollback = action.rollback(result.snapshot_entry)
    assert rollback.success is True
    assert platform.pointer_precision_enabled is True


def test_elevation_manager_writes_plan_file(tmp_path: Path):
    manager = ElevationManager(root=tmp_path)
    plan_path = manager.write_plan_file(
        {
            "plan_id": "apply-123",
            "action_ids": ["disable_telemetry", "disable_game_dvr"],
            "requires_elevation": True,
        }
    )

    assert plan_path.exists()
    assert "apply-123" in plan_path.read_text(encoding="utf-8")
    command = manager.build_apply_command(plan_path)
    assert command == [
        sys.executable,
        str(ROOT / "Tweakify.py"),
        "--apply-plan",
        str(plan_path),
    ]
    rollback = manager.build_rollback_command("snap-001")
    assert rollback == [
        sys.executable,
        str(ROOT / "Tweakify.py"),
        "--rollback-snapshot",
        "snap-001",
    ]


def test_hidden_process_kwargs_hide_windows_child_windows():
    kwargs = hidden_process_kwargs()

    assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert kwargs["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert kwargs["startupinfo"].wShowWindow == subprocess.SW_HIDE


def test_elevation_launch_uses_hidden_process_kwargs(monkeypatch, tmp_path: Path):
    manager = ElevationManager(root=tmp_path)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "app.platform.elevation.hidden_process_kwargs",
        lambda: {"creationflags": 64, "startupinfo": "hidden"},
    )

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace()

    monkeypatch.setattr("app.platform.elevation.subprocess.Popen", fake_popen)

    manager.launch_elevated(["py", str(ROOT / "Tweakify.py"), "--apply-plan", "plan.json"])

    assert captured["command"] == [
        "powershell",
        "-NoProfile",
        "-Command",
        f"Start-Process -FilePath 'py' -ArgumentList '{ROOT / 'Tweakify.py'}', '--apply-plan', 'plan.json' -Verb RunAs",
    ]
    assert captured["kwargs"] == {"creationflags": 64, "startupinfo": "hidden"}


def test_nvidia_detection_only_enables_when_binary_exists(tmp_path: Path):
    platform = InMemoryPlatformFacade()
    assert platform.detect_nvidia_inspector(tmp_path) is None

    inspector = tmp_path / "nvidiaInspector.exe"
    inspector.write_text("stub", encoding="utf-8")
    assert platform.detect_nvidia_inspector(tmp_path) == inspector


def test_windows_diagnostic_probe_handles_disk_usage_tuple(monkeypatch, tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path)

    monkeypatch.setattr(
        "app.platform.adapters.shutil.disk_usage",
        lambda _path: (100, 40, 60),
    )
    monkeypatch.setattr(platform, "startup_entry_count", lambda: 7)
    monkeypatch.setattr(platform, "top_cpu_users", lambda: ["Discord", "Steam", "SearchIndexer"])
    monkeypatch.setattr(platform, "memory_pressure", lambda: "38%")
    monkeypatch.setattr(platform, "system_drive_type", lambda: "SSD")
    monkeypatch.setattr(
        platform,
        "service_get",
        lambda name: {"start_mode": "auto" if name == "WSearch" else "manual", "running": True},
    )
    monkeypatch.setattr(platform, "registry_key_exists", lambda _path: False)
    monkeypatch.setattr(platform, "registry_get", lambda _path, _name: 1)

    snapshot = platform.diagnostic_probe()

    assert snapshot["disk_free_percent"] == "60%"
    assert snapshot["pending_updates"] == "None"


def test_windows_platform_top_cpu_users_hide_child_console(monkeypatch, tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "app.platform.adapters.hidden_process_kwargs",
        lambda: {"creationflags": 128, "startupinfo": "hidden"},
    )

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(stdout="Discord\nSteam\n", returncode=0)

    monkeypatch.setattr("app.platform.adapters.subprocess.run", fake_run)

    result = platform.top_cpu_users()

    assert result == ["Discord", "Steam"]
    assert captured["command"] == [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-Process | Sort-Object CPU -Descending | Select-Object -First 3 -ExpandProperty ProcessName",
    ]
    assert captured["kwargs"]["creationflags"] == 128
    assert captured["kwargs"]["startupinfo"] == "hidden"
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["check"] is False


def test_registry_subkey_iteration_stops_cleanly_on_winerror_259(monkeypatch, tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path)

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_open_key(_hive, _subkey, *_args, **_kwargs):
        return FakeKey()

    def fake_enum_key(_key, index):
        if index == 0:
            return "adapter0"
        if index == 1:
            return "adapter1"
        exc = OSError("No more data")
        exc.winerror = 259
        raise exc

    fake_winreg = SimpleNamespace(
        OpenKey=fake_open_key,
        EnumKey=fake_enum_key,
        KEY_WRITE=0,
        KEY_SET_VALUE=0,
        REG_DWORD=4,
    )
    monkeypatch.setitem(__import__("sys").modules, "winreg", fake_winreg)

    subkeys = list(platform._iter_registry_subkeys("HKLM", r"Some\Path"))

    assert subkeys == ["adapter0", "adapter1"]


def test_startup_inventory_reports_duplicates():
    platform = InMemoryPlatformFacade()
    platform.startup_entries = [
        {
            "id": "run:discord",
            "name": "Discord",
            "location": "Run",
            "enabled": True,
            "source_kind": "registry",
            "scope": "user",
            "registry_path": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
            "value_name": "Discord",
        },
        {
            "id": "folder:discord",
            "name": "Discord",
            "location": "Startup",
            "enabled": True,
            "source_kind": "startup_folder",
            "scope": "user",
            "file_path": r"C:\Users\Test\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\Discord.lnk",
        },
        {
            "id": "run:steam",
            "name": "Steam",
            "location": "Run",
            "enabled": True,
            "source_kind": "registry",
            "scope": "user",
            "registry_path": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
            "value_name": "Steam",
        },
    ]

    inventory = platform.startup_inventory()

    assert inventory["count"] == 3
    assert inventory["duplicates"] == ["Discord"]
    assert inventory["items"][0].source_kind in {"registry", "startup_folder"}


def test_startup_registry_entry_can_be_disabled_and_restored():
    platform = InMemoryPlatformFacade()
    entry = platform.startup_inventory()["items"][0]

    platform.startup_entry_set_enabled(entry.id, False)
    disabled = next(item for item in platform.startup_inventory()["items"] if item.id == entry.id)
    assert disabled.enabled is False

    platform.startup_entry_set_enabled(entry.id, True)
    restored = next(item for item in platform.startup_inventory()["items"] if item.id == entry.id)
    assert restored.enabled is True


def test_startup_folder_entry_can_be_disabled_and_restored():
    platform = InMemoryPlatformFacade()
    platform.startup_entries.append(
        {
            "id": "folder:obs",
            "name": "OBS",
            "location": "Startup Folder",
            "enabled": True,
            "source_kind": "startup_folder",
            "scope": "user",
            "file_path": r"C:\Users\Test\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\OBS.lnk",
        }
    )
    entry = next(item for item in platform.startup_inventory()["items"] if item.id == "folder:obs")

    platform.startup_entry_set_enabled(entry.id, False)
    disabled = next(item for item in platform.startup_inventory()["items"] if item.id == entry.id)
    assert disabled.enabled is False

    platform.startup_entry_set_enabled(entry.id, True)
    restored = next(item for item in platform.startup_inventory()["items"] if item.id == entry.id)
    assert restored.enabled is True


def test_startup_inventory_sorts_enabled_entries_first_and_preserves_status_source():
    platform = InMemoryPlatformFacade()
    platform.startup_entries = [
        {
            "id": "run:zulu",
            "name": "Zulu",
            "location": "Run",
            "enabled": False,
            "status_source": "windows_disabled",
            "command": "zulu.exe",
            "source_kind": "registry",
            "scope": "user",
            "registry_path": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
            "value_name": "Zulu",
        },
        {
            "id": "run:alpha",
            "name": "Alpha",
            "location": "Run",
            "enabled": True,
            "status_source": "active",
            "command": "alpha.exe",
            "source_kind": "registry",
            "scope": "user",
            "registry_path": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
            "value_name": "Alpha",
        },
        {
            "id": "run:beta",
            "name": "Beta",
            "location": "Run",
            "enabled": False,
            "status_source": "tweakify_disabled",
            "managed_by_tweakify": True,
            "command": "beta.exe",
            "source_kind": "registry",
            "scope": "user",
            "registry_path": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
            "value_name": "Beta",
        },
    ]

    inventory = platform.startup_inventory()

    assert [item.name for item in inventory["items"]] == ["Alpha", "Beta", "Zulu"]
    assert inventory["items"][1].status_source == "tweakify_disabled"
    assert inventory["items"][2].status_source == "windows_disabled"


def test_windows_startup_inventory_marks_run_entry_disabled_from_startupapproved(monkeypatch, tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setenv("ProgramData", str(tmp_path / "ProgramData"))

    values = {
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run": {
            "Discord": r"C:\Apps\Discord.exe --minimized",
        },
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run": {
            "Discord": bytes.fromhex("030000001122334455667788"),
        },
    }
    monkeypatch.setattr(platform, "registry_value_map", lambda path: values.get(path, {}))

    inventory = platform.startup_inventory()

    assert inventory["items"][0].name == "Discord"
    assert inventory["items"][0].enabled is False
    assert inventory["items"][0].status_source == "windows_disabled"


def test_windows_startup_inventory_marks_startup_folder_entry_disabled_from_startupapproved(monkeypatch, tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path)
    appdata = tmp_path / "AppData"
    startup_dir = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup_dir.mkdir(parents=True)
    shortcut = startup_dir / "OpenRGB.lnk"
    shortcut.write_text("stub", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("ProgramData", str(tmp_path / "ProgramData"))

    values = {
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder": {
            "OpenRGB.lnk": bytes.fromhex("010000001122334455667788"),
        },
    }
    monkeypatch.setattr(platform, "registry_value_map", lambda path: values.get(path, {}))

    inventory = platform.startup_inventory()

    assert inventory["items"][0].name == "OpenRGB"
    assert inventory["items"][0].enabled is False
    assert inventory["items"][0].status_source == "windows_disabled"


def test_windows_startup_inventory_marks_tweakify_disabled_entries_distinctly(monkeypatch, tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setenv("ProgramData", str(tmp_path / "ProgramData"))

    values = {
        r"HKCU\Software\Tweakify\DisabledStartup\Run": {
            "Spotify": r"C:\Apps\Spotify.exe --autostart",
        },
    }
    monkeypatch.setattr(platform, "registry_value_map", lambda path: values.get(path, {}))

    inventory = platform.startup_inventory()

    assert inventory["items"][0].enabled is False
    assert inventory["items"][0].managed_by_tweakify is True
    assert inventory["items"][0].status_source == "tweakify_disabled"


def test_system_theme_mode_reads_windows_personalize_setting(monkeypatch, tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path)
    monkeypatch.setattr(
        platform,
        "registry_get",
        lambda _path, _name: 0,
    )

    assert platform.system_theme_mode() == "dark"

    monkeypatch.setattr(
        platform,
        "registry_get",
        lambda _path, _name: 1,
    )
    assert platform.system_theme_mode() == "light"


def test_detect_nvidia_inspector_known_locations_avoids_recursive_search(monkeypatch, tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path)
    local_app_data = tmp_path / "LocalAppData"
    target = tmp_path / "tools" / "nvidiaInspector.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("stub", encoding="utf-8")

    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setattr(Path, "rglob", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("rglob should not be used")))

    assert platform.detect_nvidia_inspector_known_locations() == target


def test_profile_inspector_download_extracts_latest_release_to_managed_tools_dir(monkeypatch, tmp_path: Path):
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    platform = WindowsPlatformFacade(tmp_path, data_root=tmp_path / "data")

    archive_buffer = io.BytesIO()
    import zipfile

    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("nvidiaProfileInspector.exe", "stub")
        archive.writestr("CustomSettingNames.xml", "xml")
    archive_bytes = archive_buffer.getvalue()

    class FakeResponse:
        def __init__(self, payload: bytes):
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request):
        url = getattr(request, "full_url", request)
        if str(url).endswith("/releases"):
            payload = json.dumps(
                [
                    {
                        "tag_name": "v9.9.9",
                        "assets": [
                            {
                                "name": "nvidiaProfileInspector.zip",
                                "browser_download_url": "https://example.com/npi.zip",
                            }
                        ],
                    }
                ]
            ).encode("utf-8")
            return FakeResponse(payload)
        if str(url) == "https://example.com/npi.zip":
            return FakeResponse(archive_bytes)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = platform.download_nvidia_profile_inspector()

    assert result.success is True
    assert result.installed_path is not None
    assert Path(result.installed_path).name == "nvidiaProfileInspector.exe"
    assert Path(result.installed_path).exists()
    assert Path(result.installed_path).is_relative_to(tmp_path / "tools")
    assert "downloaded" in result.message.lower()
    assert platform.detect_nvidia_profile_inspector_known_locations() == Path(result.installed_path)


def test_windows_platform_uses_explicit_portable_data_root(tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path, data_root=tmp_path / "data")

    assert platform.tweakify_root == tmp_path / "data"
    assert platform.disabled_startup_dir == tmp_path / "data" / "disabled-startup"
    assert platform.profile_inspector_dir == tmp_path / "tools" / "NVIDIA Profile Inspector"


def test_profile_inspector_download_reports_failures(monkeypatch, tmp_path: Path):
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    platform = WindowsPlatformFacade(tmp_path)
    monkeypatch.setattr("urllib.request.urlopen", lambda _request: (_ for _ in ()).throw(OSError("network down")))

    result = platform.download_nvidia_profile_inspector()

    assert result.success is False
    assert result.installed_path is None
    assert "network down" in result.message.lower()


def test_windows_devmode_helper_builds_without_wintypes_short(tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path)

    devmode = platform._devmode()

    assert int(devmode.dmSize) > 0


def test_open_external_url_uses_platform_launcher(monkeypatch, tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr("os.startfile", lambda url: opened.append(url), raising=False)

    platform.open_external_url("https://example.com/tool")

    assert opened == ["https://example.com/tool"]
