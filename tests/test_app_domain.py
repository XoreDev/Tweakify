from collections import Counter
from pathlib import Path

from app.actions.catalog import build_action_catalog
from app.controller import TweakifyController
from app.domain.compatibility import CompatibilityService
from app.domain.models import (
    ActionKind,
    AppSettings,
    DiagnosticItem,
    DiagnosticsSnapshot,
    SafetyTier,
    Scope,
    SnapshotManifest,
    VerificationStatus,
)
from app.domain.presets import build_presets
from app.platform.adapters import InMemoryPlatformFacade
from app.storage.state import TweakifyStateStore
from tests.conftest import ROOT, build_controller


def test_action_catalog_has_required_modules_and_complete_metadata():
    platform = InMemoryPlatformFacade()
    actions = build_action_catalog(platform)
    module_ids = {action.definition.module_id for action in actions}

    assert {
        "performance",
        "network",
        "services",
        "cleanup",
        "input_ui",
        "graphics",
    }.issubset(module_ids)

    for action in actions:
        definition = action.definition
        assert definition.id
        assert definition.title
        assert definition.what_it_changes
        assert definition.why_it_may_help
        assert definition.downside
        assert definition.rollback
        assert definition.scope in {Scope.USER, Scope.MACHINE}
        assert definition.restart_requirement
        assert definition.safety_tier


def test_action_catalog_has_public_v2_module_density():
    platform = InMemoryPlatformFacade()
    actions = build_action_catalog(platform)
    counts = Counter(action.definition.module_id for action in actions)

    for module_id in [
        "startup",
        "performance",
        "network",
        "services",
        "cleanup",
        "input_ui",
        "graphics",
    ]:
        assert counts[module_id] >= 6


def test_presets_expand_to_known_targets_and_include_dynamic_baseline():
    platform = InMemoryPlatformFacade()
    actions = build_action_catalog(platform)
    baseline = {
        "disable_telemetry": False,
        "disable_game_dvr": False,
        "disable_auto_tuning": False,
    }
    presets = build_presets(actions, baseline_targets=baseline)
    preset_ids = {preset.id for preset in presets}

    assert {
        "baseline_restore",
        "gaming",
        "low_latency",
        "balanced",
        "privacy_minimal",
        "debloat_lite",
    }.issubset(preset_ids)
    baseline_restore = next(preset for preset in presets if preset.id == "baseline_restore")
    assert baseline_restore.action_targets == baseline


def test_presets_are_safe_dense_and_include_creator_workstation():
    platform = InMemoryPlatformFacade()
    actions = build_action_catalog(platform)
    presets = build_presets(actions, baseline_targets={})
    preset_ids = {preset.id for preset in presets}
    action_map = {action.definition.id: action for action in actions}

    assert "creator_workstation" in preset_ids
    for preset in presets:
        if preset.id == "baseline_restore":
            continue
        assert 20 <= len(preset.action_targets) <= 35
        for action_id in preset.action_targets:
            assert action_map[action_id].definition.safety_tier == SafetyTier.SAFE


def test_preset_stats_separate_compatible_already_at_target_and_real_stageable_diffs(tmp_path: Path):
    platform = InMemoryPlatformFacade(is_admin=True)
    actions = {action.definition.id: action for action in build_action_catalog(platform)}
    actions["disable_enhance_pointer_precision"].apply(True, platform.snapshot_writer())
    actions["disable_game_dvr"].apply(True, platform.snapshot_writer())
    actions["set_highest_refresh_rate"].apply(True, platform.snapshot_writer())

    controller = TweakifyController(
        platform=platform,
        storage_root=tmp_path,
    )

    stats = controller.preset_stats("gaming")
    result = controller.stage_preset("gaming")

    assert stats.compatible == stats.total
    assert stats.blocked == 0
    assert stats.already_at_target >= 3
    assert stats.will_stage == stats.total - stats.already_at_target
    assert result.added_to_review == stats.will_stage
    assert result.already_at_target == stats.already_at_target
    assert len(controller.staged_targets) == stats.will_stage


def test_every_non_baseline_preset_reports_real_stageable_diff_counts(tmp_path: Path):
    platform = InMemoryPlatformFacade(is_admin=True)
    actions = {action.definition.id: action for action in build_action_catalog(platform)}
    preset_seeds = build_presets(actions.values(), baseline_targets={})

    for preset in preset_seeds:
        if preset.id == "baseline_restore":
            continue
        for action_id in list(preset.action_targets)[:2]:
            actions[action_id].apply(True, platform.snapshot_writer())

    controller = TweakifyController(
        platform=platform,
        storage_root=tmp_path,
    )

    for preset in controller.presets:
        if preset.id == "baseline_restore":
            continue
        controller.clear_staging()
        stats = controller.preset_stats(preset.id)
        result = controller.stage_preset(preset.id)

        assert stats.compatible + stats.blocked == stats.total
        assert stats.already_at_target + stats.will_stage == stats.compatible
        assert result.added_to_review == stats.will_stage
        assert len(controller.staged_targets) == stats.will_stage


def test_snapshot_manifest_roundtrip(tmp_path: Path):
    store = TweakifyStateStore(tmp_path)
    snapshot = SnapshotManifest(
        snapshot_id="snap-001",
        created_at="2026-04-18T12:00:00Z",
        label="Baseline",
        is_baseline=True,
        machine_name="TESTBOX",
        action_entries=[],
    )
    store.save_snapshot(snapshot)

    loaded = store.load_snapshot("snap-001")
    assert loaded is not None
    assert loaded.snapshot_id == "snap-001"
    assert loaded.is_baseline is True
    assert store.list_snapshots()[0].snapshot_id == "snap-001"


def test_compatibility_blocks_nvidia_actions_without_dependency():
    platform = InMemoryPlatformFacade()
    context = platform.machine_context()
    actions = build_action_catalog(platform)
    compatibility = CompatibilityService()
    nvidia_action = next(action for action in actions if action.definition.id == "nvidia_set_max_refresh_rate")

    decision = compatibility.evaluate(context, nvidia_action.definition)

    assert decision.allowed is False
    assert any("nvidiaInspector.exe" in reason for reason in decision.reasons)


def test_controller_staging_only_tracks_differences_from_live_state(tmp_path: Path):
    platform = InMemoryPlatformFacade()
    platform.registry_set(
        r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection",
        "AllowTelemetry",
        0,
    )
    controller = TweakifyController(
        platform=platform,
        storage_root=tmp_path,
    )

    controller.stage_action("disable_telemetry", True)
    assert controller.staged_targets == {}

    controller.stage_action("disable_telemetry", False)
    assert controller.staged_targets == {"disable_telemetry": False}


def test_baseline_restore_reports_missing_baseline_snapshot(tmp_path: Path):
    store = TweakifyStateStore(tmp_path)
    store.save_settings(AppSettings(auto_capture_baseline=False))
    controller = TweakifyController(
        platform=InMemoryPlatformFacade(),
        storage_root=tmp_path,
    )

    stats = controller.preset_stats("baseline_restore")

    assert stats.enabled is False
    assert "baseline" in stats.message.lower()


def test_baseline_restore_reports_already_at_baseline_when_no_diffs_exist(tmp_path: Path):
    controller = TweakifyController(
        platform=InMemoryPlatformFacade(),
        storage_root=tmp_path,
    )

    result = controller.stage_preset("baseline_restore")

    assert result.added_to_review == 0
    assert result.already_at_target > 0
    assert "already at baseline" in result.message.lower()


def test_action_apply_reports_verification_outcome():
    platform = InMemoryPlatformFacade(is_admin=True)
    actions = {action.definition.id: action for action in build_action_catalog(platform)}
    action = actions["disable_telemetry"]

    result = action.apply(True, platform.snapshot_writer())

    assert result.success is True
    assert result.verification_status == VerificationStatus.VERIFIED
    assert result.effective_value is True


def test_every_allowed_setting_action_captures_reversible_snapshot_entry():
    compatibility = CompatibilityService()

    for action in build_action_catalog(InMemoryPlatformFacade(is_admin=True)):
        if action.definition.kind != ActionKind.SETTING:
            continue

        platform = InMemoryPlatformFacade(is_admin=True)
        if action.definition.requires_dependency == "nvidiaInspector.exe":
            stub = ROOT / "tools" / "nvidiaInspector.exe"
            stub.parent.mkdir(parents=True, exist_ok=True)
            stub.write_text("stub", encoding="utf-8")
            platform.nvidia_path = stub
        action_instance = {
            candidate.definition.id: candidate for candidate in build_action_catalog(platform)
        }[action.definition.id]
        decision = compatibility.evaluate(platform.machine_context(), action_instance.definition)
        if not decision.allowed:
            continue

        writer = platform.snapshot_writer()
        current_state = bool(action_instance.probe().current_state)
        result = action_instance.apply(not current_state, writer)

        assert result.snapshot_entry is not None, action_instance.definition.id
        assert writer.entries, action_instance.definition.id
        rollback = action_instance.rollback(result.snapshot_entry)
        assert rollback.success is True, action_instance.definition.id


def test_apply_staged_captures_startup_entry_snapshot_and_supports_rollback(tmp_path: Path):
    platform = InMemoryPlatformFacade(is_admin=True)
    controller = TweakifyController(
        platform=platform,
        storage_root=tmp_path,
    )
    entry = controller.startup_inventory["items"][0]

    controller.stage_startup_entry(entry.id, False)
    transaction = controller.apply_staged()

    assert any(result.action_id == entry.id for result in transaction.results)
    snapshots = controller.store.list_snapshots()
    assert snapshots
    assert any(snapshot_entry.action_id == entry.id for snapshot_entry in snapshots[0].action_entries)
    applied_state = next(item for item in platform.startup_inventory()["items"] if item.id == entry.id)
    assert applied_state.enabled is False

    rollback = controller.rollback_snapshot(snapshots[0].snapshot_id)

    assert any(result.action_id == entry.id for result in rollback.results)
    restored_state = next(item for item in platform.startup_inventory()["items"] if item.id == entry.id)
    assert restored_state.enabled is True


def test_state_store_persists_app_settings(tmp_path: Path):
    store = TweakifyStateStore(tmp_path)
    settings = AppSettings(
        theme_mode="dark",
        accent_intensity=0.72,
        compact_mode=True,
        reduced_motion=False,
        font_scale=1.05,
        auto_preview=True,
        confirm_before_apply=True,
        auto_capture_baseline=True,
        auto_restore_point_advanced=True,
        review_tray_open=True,
        auto_open_review_drawer=False,
        diagnostics_refresh_on_launch=True,
        diagnostics_refresh_interval_seconds=180,
        diagnostics_background_poll=False,
        diagnostics_cache_retention_days=7,
        nvidia_inspector_path=r"C:\Tools\nvidiaInspector.exe",
        nvidia_profile_inspector_path=r"C:\Tools\nvidiaProfileInspector.exe",
        show_advanced=True,
        show_experimental=False,
        strict_confirmation=True,
    )

    store.save_settings(settings)
    loaded = store.load_settings()

    assert loaded == settings


def test_profile_inspector_setting_does_not_enable_legacy_nvidia_actions(tmp_path: Path):
    store = TweakifyStateStore(tmp_path)
    store.save_settings(AppSettings(nvidia_profile_inspector_path=r"C:\Tools\nvidiaProfileInspector.exe"))
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())

    decision = controller.compatibility_by_action["nvidia_set_max_refresh_rate"]

    assert controller.settings.nvidia_profile_inspector_path.endswith("nvidiaProfileInspector.exe")
    assert decision.allowed is False
    assert any("nvidiaInspector.exe" in reason for reason in decision.reasons)


def test_light_startup_profile_skips_live_runtime_scans_and_uses_cached_diagnostics(tmp_path: Path, monkeypatch):
    store = TweakifyStateStore(tmp_path)
    cached = DiagnosticsSnapshot(
        captured_at="2026-04-19T00:00:00Z",
        items=[
            DiagnosticItem(
                id="cached",
                title="Cached Diagnostics",
                value="Ready",
                status="info",
                detail="Cached during the previous run.",
            )
        ],
    )
    store.save_diagnostics(cached)
    platform = InMemoryPlatformFacade()

    monkeypatch.setattr(
        platform,
        "machine_context",
        lambda: (_ for _ in ()).throw(AssertionError("full machine context should not run during light startup")),
    )
    monkeypatch.setattr(
        platform,
        "startup_inventory",
        lambda: (_ for _ in ()).throw(AssertionError("startup inventory should not run during light startup")),
    )
    monkeypatch.setattr(
        "app.platform.diagnostics.DiagnosticsCollector.collect",
        lambda self, startup_inventory=None: (_ for _ in ()).throw(
            AssertionError("live diagnostics should not run during light startup")
        ),
    )

    controller = TweakifyController(
        platform=platform,
        storage_root=tmp_path,
        startup_profile="light",
    )

    assert controller.runtime_pending is True
    assert controller.action_states["disable_telemetry"].current_state is None
    assert controller.startup_inventory == {"count": 0, "duplicates": [], "items": []}
    assert controller.startup_inventory_by_id == {}
    assert controller.diagnostics == cached
    assert controller.store.latest_baseline() is None


def test_build_runtime_snapshot_avoids_duplicate_inventory_and_reuses_probe_cache(tmp_path: Path):
    platform = InMemoryPlatformFacade()
    controller = TweakifyController(
        platform=platform,
        storage_root=tmp_path,
        startup_profile="light",
    )
    call_counts = {
        "startup_inventory": 0,
        "display_get_current_refresh_rate": 0,
        "display_get_highest_refresh_rate": 0,
        "power_get_active_plan": 0,
    }

    for name in list(call_counts):
        original = getattr(platform, name)

        def make_wrapper(method_name, method):
            def wrapper(*args, **kwargs):
                call_counts[method_name] += 1
                return method(*args, **kwargs)

            return wrapper

        setattr(platform, name, make_wrapper(name, original))

    snapshot = controller.build_runtime_snapshot(force_live_diagnostics=True)

    assert snapshot["startup_inventory"]["count"] == len(platform.startup_entries)
    assert call_counts["startup_inventory"] == 1
    assert call_counts["display_get_current_refresh_rate"] == 1
    assert call_counts["display_get_highest_refresh_rate"] == 1
    assert call_counts["power_get_active_plan"] == 1


def test_build_runtime_snapshot_can_skip_live_diagnostics_and_keep_cached_snapshot(tmp_path: Path, monkeypatch):
    store = TweakifyStateStore(tmp_path)
    store.save_settings(AppSettings(diagnostics_refresh_on_launch=False))
    cached = DiagnosticsSnapshot(
        captured_at="2026-04-19T00:00:00Z",
        items=[
            DiagnosticItem(
                id="cached",
                title="Cached Diagnostics",
                value="Ready",
                status="info",
                detail="Cached during the previous run.",
            )
        ],
    )
    store.save_diagnostics(cached)
    platform = InMemoryPlatformFacade()
    controller = TweakifyController(
        platform=platform,
        storage_root=tmp_path,
        startup_profile="light",
    )

    monkeypatch.setattr(
        platform,
        "diagnostic_probe",
        lambda startup_count=None: (_ for _ in ()).throw(
            AssertionError("live diagnostics should be skipped when launch refresh is disabled")
        ),
    )

    snapshot = controller.build_runtime_snapshot(force_live_diagnostics=False)

    assert snapshot["diagnostics"] == cached


def test_capture_initial_baseline_if_needed_is_deferred_until_requested(tmp_path: Path):
    store = TweakifyStateStore(tmp_path)
    store.save_settings(AppSettings(auto_capture_baseline=True))
    controller = TweakifyController(
        platform=InMemoryPlatformFacade(),
        storage_root=tmp_path,
        startup_profile="light",
    )

    assert controller.store.latest_baseline() is None

    manifest = controller.capture_initial_baseline_if_needed()

    assert manifest is not None
    assert controller.store.latest_baseline() is not None
