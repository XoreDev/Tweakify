"""Regression tests for the bugs found in the 2026-11 audit, plus the features added with it."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.__main__ import _apply_cli_request, _build_parser
from app.actions.base import BaseEffect, EffectAction
from app.actions.catalog import build_action_catalog
from app.actions.cleanup import WEEKLY_CLEANUP_TASK
from app.domain.models import AppSettings, SafetyTier, SnapshotWriter
from app.domain.presets import build_presets
from app.platform.adapters import InMemoryPlatformFacade, WindowsPlatformFacade
from app.storage.state import TweakifyStateStore
from tests.conftest import build_controller


def _actions(platform):
    return {action.definition.id: action for action in build_action_catalog(platform)}


class _Completed(SimpleNamespace):
    pass


# --------------------------------------------------------------------------- platform: services


def test_service_set_passes_start_and_mode_as_separate_arguments(monkeypatch, tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path, data_root=tmp_path / "data")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return _Completed(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(platform, "_run_hidden", fake_run)
    platform.service_set("DiagTrack", "disabled")

    assert calls == [["sc", "config", "DiagTrack", "start=", "disabled"]]


def test_service_set_raises_when_sc_rejects_the_change(monkeypatch, tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path, data_root=tmp_path / "data")
    monkeypatch.setattr(platform, "_run_hidden", lambda command, **kwargs: _Completed(returncode=5, stdout="Access is denied.", stderr=""))

    with pytest.raises(RuntimeError, match="Access is denied"):
        platform.service_set("DiagTrack", "disabled")


def test_service_probe_reports_missing_and_delayed_auto(monkeypatch, tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path, data_root=tmp_path / "data")

    def fake_run(command, **kwargs):
        if command[1] == "qc" and command[2] == "Gone":
            return _Completed(returncode=1060, stdout="", stderr="")
        if command[1] == "qc":
            return _Completed(returncode=0, stdout="        START_TYPE         : 2   AUTO_START  (DELAYED)\n", stderr="")
        return _Completed(returncode=0, stdout="STATE : 4  RUNNING", stderr="")

    monkeypatch.setattr(platform, "_run_hidden", fake_run)

    assert platform.service_get("Gone") == {"start_mode": "missing", "running": False}
    assert platform.service_get("WSearch") == {"start_mode": "delayed-auto", "running": True}


def test_missing_service_is_skipped_instead_of_failing_the_apply():
    platform = InMemoryPlatformFacade(is_admin=True)
    platform.services.pop("XblGameSave")
    action = _actions(platform)["disable_xbox_services"]

    result = action.apply(True, SnapshotWriter())

    assert result.success is True
    assert platform.services["XblAuthManager"]["start_mode"] == "disabled"


# --------------------------------------------------------------------------- engine: apply / rollback safety


class _ExplodingEffect(BaseEffect):
    def capture_state(self):
        return {}

    def restore_state(self, state):
        return None

    def is_enabled(self):
        return False

    def plan_commands(self, target_state):
        return ["explode"]

    def apply_target(self, target_state):
        raise RuntimeError("boom")


def test_failed_action_reverts_its_partial_changes_and_keeps_a_snapshot(tmp_path: Path):
    platform = InMemoryPlatformFacade(is_admin=True)
    controller = build_controller(tmp_path, platform=platform)
    telemetry = controller.actions_by_id["disable_telemetry"]
    # Make the action write its policy and then fail on a second effect.
    telemetry.effects.append(_ExplodingEffect(platform))

    controller.stage_action("disable_telemetry", True)
    controller.stage_action("disable_advertising_id", True)
    transaction = controller.apply_staged()

    by_id = {result.action_id: result for result in transaction.results}
    assert by_id["disable_telemetry"].success is False
    assert "boom" in by_id["disable_telemetry"].message
    assert "reverted" in by_id["disable_telemetry"].message
    # The half-applied policy was put back.
    assert platform.registry_get(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry") is None
    # The action after it still ran.
    assert by_id["disable_advertising_id"].success is True
    # And the snapshot was saved even though one action failed.
    snapshot = controller.store.load_snapshot(transaction.snapshot_id)
    assert {entry.action_id for entry in snapshot.action_entries} == {"disable_telemetry", "disable_advertising_id"}


def test_rollback_restores_in_reverse_order(tmp_path: Path):
    platform = InMemoryPlatformFacade(is_admin=True)
    controller = build_controller(tmp_path, platform=platform)
    order = []
    for action_id in ("disable_telemetry", "disable_advertising_id"):
        action = controller.actions_by_id[action_id]
        original = action.rollback
        action.rollback = lambda entry, _original=original, _id=action_id: (order.append(_id), _original(entry))[1]
        controller.stage_action(action_id, True)

    transaction = controller.apply_staged()
    controller.rollback_snapshot(transaction.snapshot_id)

    assert order == ["disable_advertising_id", "disable_telemetry"]


def test_policy_tweaks_delete_the_policy_when_turned_off():
    platform = InMemoryPlatformFacade(is_admin=True)
    actions = _actions(platform)
    path = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\System"

    actions["disable_smartscreen"].apply(True, SnapshotWriter())
    assert platform.registry_get(path, "EnableSmartScreen") == 0
    actions["disable_smartscreen"].apply(False, SnapshotWriter())

    # Writing EnableSmartScreen=1 instead would lock the setting as "managed by your organization".
    assert platform.registry_get(path, "EnableSmartScreen") is None


def test_rollback_preserves_the_original_registry_value_type():
    platform = InMemoryPlatformFacade(is_admin=True)
    path, name = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run", "OneDrive"
    platform.registry_set(path, name, r"%LOCALAPPDATA%\OneDrive.exe /background", "REG_EXPAND_SZ")
    writer = SnapshotWriter()
    action = _actions(platform)["disable_onedrive_startup"]

    action.apply(True, writer)
    assert platform.registry_get(path, name) is None
    action.rollback(writer.entries[0])

    assert platform.registry_get_typed(path, name) == (r"%LOCALAPPDATA%\OneDrive.exe /background", "REG_EXPAND_SZ")


def test_interface_values_roll_back_per_adapter():
    platform = InMemoryPlatformFacade(is_admin=True)
    platform.interface_values = {"wifi": {"TcpAckFrequency": 2}, "ethernet": {}}
    writer = SnapshotWriter()
    action = _actions(platform)["disable_nagle_algorithm"]

    action.apply(True, writer)
    assert platform.interface_values["ethernet"]["TcpAckFrequency"] == 1
    action.rollback(writer.entries[0])

    assert platform.interface_values["wifi"] == {"TcpAckFrequency": 2}
    assert platform.interface_values["ethernet"] == {}


def test_missing_scheduled_tasks_do_not_count_as_failures():
    platform = InMemoryPlatformFacade(is_admin=True)
    platform.scheduled_tasks.clear()
    action = _actions(platform)["disable_ceip_tasks"]

    result = action.apply(True, SnapshotWriter())

    assert action.is_enabled() is None
    assert result.success is True


# --------------------------------------------------------------------------- catalog correctness


def test_priority_separation_tweak_is_not_the_windows_default():
    platform = InMemoryPlatformFacade(is_admin=True)
    action = _actions(platform)["optimize_cpu_priority"]
    action.apply(True, SnapshotWriter())

    value = platform.registry_get(r"HKLM\SYSTEM\CurrentControlSet\Control\PriorityControl", "Win32PrioritySeparation")
    assert value == 0x26 and value != 2


def test_temp_cleanup_expands_the_wildcard_and_tolerates_locked_files():
    platform = InMemoryPlatformFacade(is_admin=True)
    action = _actions(platform)["clear_temp_files"]
    script = action.effects[0].command[-1]

    assert "-LiteralPath $env:TEMP\\*" not in script
    assert "Get-ChildItem -LiteralPath $dir" in script
    assert script.rstrip().endswith("exit 0")


def test_disk_cleanup_runs_unattended():
    platform = InMemoryPlatformFacade(is_admin=True)
    script = _actions(platform)["disk_cleanup"].effects[0].command[-1]

    assert "/sagerun:777" in script
    assert "StateFlags0777" in script


def test_search_index_reset_stops_the_service_before_deleting():
    platform = InMemoryPlatformFacade(is_admin=True)
    script = _actions(platform)["reset_search_index"].effects[0].command[-1]

    assert script.index("Stop-Service -Name WSearch") < script.index("Remove-Item")
    assert "Windows*.db" in script


def test_maintenance_reports_failure_on_bad_exit_code():
    platform = InMemoryPlatformFacade(is_admin=True)
    platform.command_return_codes["chkdsk"] = 3
    result = _actions(platform)["check_disk_errors"].apply(True, SnapshotWriter())

    assert result.success is False
    assert "code 3" in result.message


def test_no_preset_turns_on_mouse_trails_and_all_stay_safe():
    platform = InMemoryPlatformFacade()
    actions = build_action_catalog(platform)
    action_map = {action.definition.id: action for action in actions}
    for preset in build_presets(actions):
        assert "adjust_mouse_trails" not in preset.action_targets
        for action_id in preset.action_targets:
            assert action_map[action_id].definition.safety_tier == SafetyTier.SAFE


def test_nvidia_actions_write_real_driver_setting_ids(tmp_path: Path):
    platform = InMemoryPlatformFacade(is_admin=True)
    platform.profile_inspector_path = tmp_path / "nvidiaProfileInspector.exe"
    writer = SnapshotWriter()
    action = _actions(platform)["nvidia_prefer_maximum_performance"]

    action.apply(True, writer)
    action.rollback(writer.entries[0])

    # Power management mode -> Prefer maximum performance, then back to the driver default.
    assert platform.nvidia_profile_imports == [{0x1057EB71: 1}, {0x1057EB71: 5}]


# --------------------------------------------------------------------------- storage


def test_settings_with_unknown_or_wrongly_typed_keys_still_load(tmp_path: Path):
    store = TweakifyStateStore(tmp_path)
    store.settings_path.write_text(
        json.dumps({"theme_mode": "dark", "from_a_future_version": 1, "font_scale": "huge", "accent_intensity": 1}),
        encoding="utf-8",
    )

    settings = store.load_settings()

    assert settings.theme_mode == "dark"
    assert settings.font_scale == AppSettings().font_scale
    assert settings.accent_intensity == 1.0


def test_corrupt_settings_file_is_kept_and_defaults_are_used(tmp_path: Path):
    store = TweakifyStateStore(tmp_path)
    store.settings_path.write_text("{not json", encoding="utf-8")

    assert store.load_settings() == AppSettings()
    assert (tmp_path / "settings.corrupt.json").exists()


def test_corrupt_snapshot_is_skipped_not_fatal(tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    (controller.store.snapshots_dir / "broken.json").write_text("{", encoding="utf-8")

    assert all(snapshot.snapshot_id != "broken" for snapshot in controller.store.list_snapshots())
    assert controller.store.load_snapshot("..\\settings") is None


# --------------------------------------------------------------------------- features


def test_staging_a_power_plan_replaces_the_conflicting_one(tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade(is_admin=True))

    controller.stage_action("high_performance_power_plan", True)
    controller.stage_action("ultimate_performance_power_plan", True)

    assert "high_performance_power_plan" not in controller.staged_targets
    assert controller.staged_targets["ultimate_performance_power_plan"] is True
    assert "replaces" in controller.last_stage_notice


def test_dns_provider_applies_and_restores_each_adapter(tmp_path: Path):
    platform = InMemoryPlatformFacade(is_admin=True)
    platform.dns_servers = {"Ethernet": [], "Wi-Fi": ["192.168.1.1"]}
    writer = SnapshotWriter()
    action = _actions(platform)["dns_cloudflare"]

    action.apply(True, writer)
    assert platform.dns_servers == {"Ethernet": ["1.1.1.1", "1.0.0.1"], "Wi-Fi": ["1.1.1.1", "1.0.0.1"]}
    action.rollback(writer.entries[0])

    assert platform.dns_servers == {"Ethernet": [], "Wi-Fi": ["192.168.1.1"]}


def test_plan_export_and_import_roundtrip(tmp_path: Path):
    source = build_controller(tmp_path / "a", platform=InMemoryPlatformFacade(is_admin=True))
    source.stage_action("disable_advertising_id", True)
    source.stage_action("clear_temp_files", True)
    plan_path = source.export_staged_plan(tmp_path / "plan.json")

    target = build_controller(tmp_path / "b", platform=InMemoryPlatformFacade(is_admin=True))
    skipped = target.import_plan(plan_path)

    assert skipped == []
    assert target.staged_targets == {"disable_advertising_id": True, "clear_temp_files": True}


def test_health_report_scores_findings_and_stages_only_safe_fixes(tmp_path: Path):
    platform = InMemoryPlatformFacade(is_admin=True)
    platform.diagnostics["ram_pressure"] = "90%"
    platform.diagnostics["disk_free_percent"] = "8%"
    controller = build_controller(tmp_path, platform=platform)
    controller.cleanup_sizes = {"temp": 6 * 1024**3}

    report = controller.health_report()
    assert report.score < 60
    assert report.recoverable_bytes == 6 * 1024**3
    assert report.findings[0].severity == "critical"

    added = controller.stage_recommended_fixes()
    assert added > 0
    for action_id in controller.staged_targets:
        assert controller.actions_by_id[action_id].definition.safety_tier == SafetyTier.SAFE


def test_weekly_cleanup_registers_and_removes_a_scheduled_task():
    platform = InMemoryPlatformFacade(is_admin=True)
    writer = SnapshotWriter()
    action = _actions(platform)["schedule_weekly_cleanup"]

    action.apply(True, writer)
    assert platform.scheduled_tasks[WEEKLY_CLEANUP_TASK]["arguments"][0] == "--run-actions"
    action.rollback(writer.entries[0])

    assert WEEKLY_CLEANUP_TASK not in platform.scheduled_tasks


def test_cli_run_actions_returns_nonzero_when_an_action_fails(tmp_path: Path, capsys):
    platform = InMemoryPlatformFacade(is_admin=True)
    platform.command_return_codes["chkdsk"] = 3
    controller = build_controller(tmp_path, platform=platform)
    args = _build_parser().parse_args(["--run-actions", "check_disk_errors,flush_dns_cache,not_real"])

    code = _apply_cli_request(controller, args)

    output = capsys.readouterr()
    assert code == 1
    assert "FAIL" in output.out and "Unknown action id: not_real" in output.err


def test_failed_restore_point_is_reported_in_the_transaction(tmp_path: Path):
    platform = InMemoryPlatformFacade(is_admin=True)
    platform.restore_point_result = False
    controller = build_controller(tmp_path, platform=platform)
    controller.stage_action("disable_smartscreen", True)

    transaction = controller.apply_staged()

    assert any("could not create a restore point" in note for note in transaction.notes)


def test_non_admin_apply_does_not_launch_uac_from_test_platforms(tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade(is_admin=False))
    controller.stage_action("disable_telemetry", True)

    transaction = controller.apply_staged()

    assert transaction.requested_elevation is True
    assert any("saved to" in note for note in transaction.notes)


def test_power_setting_probe_parses_ac_and_dc_indexes(monkeypatch, tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path, data_root=tmp_path / "data")
    output = (
        "    Power Setting GUID: 48e6b7a6-50f5-4782-a5d4-53bb8f07e226  (USB selective suspend setting)\n"
        "      Possible Setting Index: 000\n"
        "    Current AC Power Setting Index: 0x00000001\n"
        "    Current DC Power Setting Index: 0x00000000\n"
    )
    monkeypatch.setattr(platform, "_run_hidden", lambda command, **kwargs: _Completed(returncode=0, stdout=output, stderr=""))

    assert platform.power_setting_get("sub", "setting") == {"ac": 1, "dc": 0}


def test_startup_folder_scan_ignores_desktop_ini(monkeypatch, tmp_path: Path):
    startup = tmp_path / "AppData" / r"Microsoft\Windows\Start Menu\Programs\Startup"
    startup.mkdir(parents=True)
    (startup / "desktop.ini").write_text("[.ShellClassInfo]", encoding="utf-8")
    (startup / "Spotify.lnk").write_text("lnk", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setenv("ProgramData", str(tmp_path / "ProgramData"))
    platform = WindowsPlatformFacade(tmp_path, data_root=tmp_path / "data")
    monkeypatch.setattr(platform, "registry_value_map", lambda path: {})

    names = [item.name for item in platform.startup_inventory()["items"]]

    assert names == ["Spotify"]


# --------------------------------------------------------------------------- community tool features


def test_game_priority_targets_only_listed_executables(tmp_path: Path):
    from app.actions.game_profiles import IFEO, parse_game_executables

    assert parse_game_executables('cs2, "C:/Games/Fortnite.exe"; explorer.exe; cs2.exe; bad|name') == ["cs2.exe", "Fortnite.exe"]

    platform = InMemoryPlatformFacade(is_admin=True)
    controller = build_controller(tmp_path, platform=platform)
    assert controller.compatibility_by_action["game_cpu_priority"].allowed is False

    controller.update_setting("game_executables", "cs2.exe")
    assert controller.compatibility_by_action["game_cpu_priority"].allowed is True
    controller.stage_action("game_cpu_priority", True)
    transaction = controller.apply_staged()
    assert transaction.results[0].success is True
    assert platform.registry_get(rf"{IFEO}\cs2.exe\PerfOptions", "CpuPriorityClass") == 3

    controller.rollback_snapshot(transaction.snapshot_id)
    assert platform.registry_get(rf"{IFEO}\cs2.exe\PerfOptions", "CpuPriorityClass") is None


def test_nic_property_tweak_restores_each_adapter():
    platform = InMemoryPlatformFacade(is_admin=True)
    platform.net_adapter_properties = {"Ethernet": {"*EEE": "1"}, "Ethernet 2": {"*EEE": "0"}, "Wi-Fi": {}}
    writer = SnapshotWriter()
    action = _actions(platform)["disable_energy_efficient_ethernet"]

    action.apply(True, writer)
    assert platform.net_adapter_properties["Ethernet"]["*EEE"] == "0"
    assert "Wi-Fi" not in [line.split(":")[1] for line in platform.command_log if line.startswith("nic:")]
    action.rollback(writer.entries[0])

    assert platform.net_adapter_properties == {"Ethernet": {"*EEE": "1"}, "Ethernet 2": {"*EEE": "0"}, "Wi-Fi": {}}


def test_remove_forced_hpet_deletes_and_restores_the_boot_value():
    platform = InMemoryPlatformFacade(is_admin=True)
    platform.bcd_values = {"useplatformclock": "Yes"}
    writer = SnapshotWriter()
    action = _actions(platform)["remove_forced_hpet"]

    assert action.is_enabled() is False
    action.apply(True, writer)
    assert "useplatformclock" not in platform.bcd_values
    action.rollback(writer.entries[0])

    assert platform.bcd_values == {"useplatformclock": "Yes"}


def test_bcd_probe_parses_bcdedit_output(monkeypatch, tmp_path: Path):
    platform = WindowsPlatformFacade(tmp_path, data_root=tmp_path / "data")
    output = "Windows Boot Loader\n-------------------\nidentifier              {current}\nuseplatformclock        Yes\nnx                      OptIn\n"
    monkeypatch.setattr(platform, "_run_hidden", lambda command, **kwargs: _Completed(returncode=0, stdout=output, stderr=""))

    assert platform.bcd_get("useplatformclock") == "Yes"
    assert platform.bcd_get("disabledynamictick") is None


def test_disable_all_startup_stages_every_enabled_entry(tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade(is_admin=True))

    count = controller.stage_disable_all_startup()

    assert count == len(controller.startup_inventory["items"])
    assert set(controller.staged_startup_entries.values()) == {False}


def test_teredo_policy_is_removed_when_turned_off():
    platform = InMemoryPlatformFacade(is_admin=True)
    action = _actions(platform)["disable_teredo"]
    path = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\TCPIP\v6Transition"

    action.apply(True, SnapshotWriter())
    assert platform.registry_get_typed(path, "Teredo_State") == ("Disabled", "REG_SZ")
    action.apply(False, SnapshotWriter())

    assert platform.registry_get(path, "Teredo_State") is None
