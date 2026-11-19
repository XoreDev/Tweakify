"""Tests for the 1.2 performance work: scoped probe cache, parallel scans, live sampler."""

import threading
from pathlib import Path

from app.platform.adapters import InMemoryPlatformFacade
from app.platform.live import LiveSample, SyntheticLiveSampler
from tests.conftest import build_controller


def test_probe_cache_is_scoped_to_the_session_that_opened_it():
    platform = InMemoryPlatformFacade()
    calls: list[int] = []

    def loader():
        calls.append(1)
        return len(calls)

    with platform.probe_session():
        assert platform._cached_probe(("k",), loader) == 1
        assert platform._cached_probe(("k",), loader) == 1

        seen_from_other_thread: list[int] = []
        worker = threading.Thread(target=lambda: seen_from_other_thread.append(platform._cached_probe(("k",), loader)))
        worker.start()
        worker.join()

    # A thread that did not join the session (e.g. an Apply) must read live values.
    assert seen_from_other_thread == [2]
    # Outside any session nothing is cached.
    assert platform._cached_probe(("k",), loader) == 3


def test_bound_workers_share_one_load_per_key():
    platform = InMemoryPlatformFacade()
    calls: list[int] = []
    gate = threading.Event()

    def loader():
        gate.wait(1)
        calls.append(1)
        return "value"

    with platform.probe_session():
        bound = platform.bind_probe_session(lambda: platform._cached_probe(("shared",), loader))
        results: list[str] = []
        threads = [threading.Thread(target=lambda: results.append(bound())) for _ in range(6)]
        for thread in threads:
            thread.start()
        gate.set()
        for thread in threads:
            thread.join()

    assert results == ["value"] * 6
    assert len(calls) == 1


def test_parallel_runtime_snapshot_matches_serial_snapshot(tmp_path: Path):
    serial_platform = InMemoryPlatformFacade()
    parallel_platform = InMemoryPlatformFacade()
    parallel_platform.probe_workers = 6

    serial = build_controller(tmp_path / "serial", platform=serial_platform).build_runtime_snapshot()
    parallel = build_controller(tmp_path / "parallel", platform=parallel_platform).build_runtime_snapshot()

    assert {key: value.current_state for key, value in serial["action_states"].items()} == {
        key: value.current_state for key, value in parallel["action_states"].items()
    }
    assert set(serial["compatibility_by_action"]) == set(parallel["compatibility_by_action"])


def test_parallel_baseline_capture_records_every_setting(tmp_path: Path):
    platform = InMemoryPlatformFacade()
    platform.probe_workers = 6
    controller = build_controller(tmp_path, platform=platform)

    manifest = controller.capture_new_baseline()

    setting_ids = {action.definition.id for action in controller.actions if action.definition.kind.value == "setting"}
    assert {entry.action_id for entry in manifest.action_entries} == setting_ids


def test_synthetic_live_sampler_produces_bounded_values():
    sampler = SyntheticLiveSampler()
    samples = [sampler.sample() for _ in range(50)]
    assert all(isinstance(sample, LiveSample) for sample in samples)
    for sample in samples:
        for value in (sample.cpu_percent, sample.memory_percent, sample.gpu_percent, sample.disk_percent):
            assert value is not None and 0 <= value <= 100
        assert 0 < sample.memory_used_bytes < sample.memory_total_bytes


NEW_SETTING_TWEAKS = {
    "disable_vbs_memory_integrity": (r"HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard", "EnableVirtualizationBasedSecurity", 0),
    "disable_delivery_optimization_p2p": (r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization", "DODownloadMode", 0),
    "disable_8dot3_name_creation": (r"HKLM\SYSTEM\CurrentControlSet\Control\FileSystem", "NtfsDisable8dot3NameCreation", 1),
    "disable_automatic_maintenance": (r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\Maintenance", "MaintenanceDisabled", 1),
    "disable_transparency_effects": (r"HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency", 0),
}


def test_new_setting_tweaks_apply_and_roll_back_exactly(tmp_path: Path):
    platform = InMemoryPlatformFacade(is_admin=True)
    platform.registry_set(r"HKLM\SYSTEM\CurrentControlSet\Control\FileSystem", "NtfsDisable8dot3NameCreation", 2)
    platform.registry_set(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency", 1)
    controller = build_controller(tmp_path, platform=platform)
    controller.update_setting("show_advanced", True)
    controller.refresh_visibility_only()
    before = {action_id: platform.registry_get(path, name) for action_id, (path, name, _value) in NEW_SETTING_TWEAKS.items()}

    for action_id in NEW_SETTING_TWEAKS:
        controller.stage_action(action_id, True)
    transaction = controller.apply_staged()

    assert not transaction.failed_results, [result.message for result in transaction.failed_results]
    for action_id, (path, name, value) in NEW_SETTING_TWEAKS.items():
        assert platform.registry_get(path, name) == value, action_id

    controller.rollback_snapshot(controller.store.list_snapshots()[0].snapshot_id)
    for action_id, (path, name, _value) in NEW_SETTING_TWEAKS.items():
        assert platform.registry_get(path, name) == before[action_id], action_id


def test_free_standby_memory_is_a_one_shot_that_reports_refusal(tmp_path: Path):
    platform = InMemoryPlatformFacade(is_admin=True)
    controller = build_controller(tmp_path, platform=platform)
    controller.stage_action("free_standby_memory", True)
    assert not controller.apply_staged().failed_results
    assert "purge-standby-list" in platform.command_log

    platform.is_admin = False
    action = controller.actions_by_id["free_standby_memory"]
    try:
        action.effects[0].apply_target(True)
    except Exception as exc:  # ActionFailure
        assert "administrator" in str(exc)
    else:
        raise AssertionError("a refused purge must raise")


def test_platform_exposes_live_sampler_and_standby_purge():
    platform = InMemoryPlatformFacade(is_admin=True)
    assert platform.create_live_sampler().sample().cpu_percent is not None
    assert platform.purge_standby_list() is True
    assert "purge-standby-list" in platform.command_log
