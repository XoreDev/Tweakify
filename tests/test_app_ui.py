from pathlib import Path

from PySide6.QtCore import Qt

from app.controller import MODULES
from app.platform.adapters import InMemoryPlatformFacade
from app.ui.main_window import TweakifyMainWindow
from app.ui.widgets import ToggleSwitch
from tests.conftest import build_controller


def _window(tmp_path: Path, **platform_kwargs) -> TweakifyMainWindow:
    return TweakifyMainWindow(build_controller(tmp_path, platform=InMemoryPlatformFacade(**platform_kwargs)))


def _page_index(module_id: str) -> int:
    return next(index for index, (mid, _label) in enumerate(MODULES) if mid == module_id)


def test_dashboard_surfaces_admin_privilege_note(qapp, tmp_path: Path):
    window = _window(tmp_path)
    assert "administrator privileges" in window.dashboard_page.admin_notice_label.text().lower()


def test_main_window_renders_sidebar_and_dashboard(qapp, tmp_path: Path):
    window = _window(tmp_path)

    assert [button.text() for button in window.sidebar_buttons] == [label for _module_id, label in MODULES]
    assert window.dashboard_page.title_label.text() == "Dashboard"
    assert window.dashboard_page.metrics_layout.count() >= 5
    assert window.dashboard_page.scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    # 1.2: the review panel stays out of the way until something is staged.
    assert window.review_drawer.isVisible() is False


def test_staging_updates_review_panel_and_opens_it_without_mutating_machine(qapp, tmp_path: Path):
    platform = InMemoryPlatformFacade()
    controller = build_controller(tmp_path, platform=platform)
    window = TweakifyMainWindow(controller)

    window.action_cards["disable_telemetry"].set_target_state(True)

    assert controller.staged_targets["disable_telemetry"] is True
    assert "1 pending" in window.review_tray.summary_label.text().lower()
    assert window.review_drawer.isVisible() is True
    assert window.review_launcher.text() == "Review  ·  1"
    assert window.review_launcher.property("pending") is True
    assert platform.registry_get(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry") is None


def test_review_panel_hides_again_when_staging_is_cleared(qapp, tmp_path: Path):
    window = _window(tmp_path)
    window.action_cards["disable_telemetry"].set_target_state(True)
    assert window.review_drawer.isVisible() is True

    window.review_drawer.clear()

    assert window.review_drawer.isVisible() is False
    assert "discarded" in window.review_drawer.plan_text.toPlainText().lower()


def test_review_panel_can_be_closed_and_reopened_from_the_top_bar(qapp, tmp_path: Path):
    window = _window(tmp_path)
    window.action_cards["disable_telemetry"].set_target_state(True)

    window.review_drawer.close_button.click()
    assert window.review_drawer.isVisible() is False

    window.review_launcher.click()
    assert window.review_drawer.isVisible() is True


def test_review_panel_pin_setting_keeps_it_open(qapp, tmp_path: Path):
    window = _window(tmp_path)
    assert "review_tray_open" in window.settings_page.controls

    window._handle_setting_change("review_tray_open", True)
    assert window.review_drawer.isVisible() is True

    window._handle_setting_change("review_tray_open", False)
    assert window.review_drawer.isVisible() is False


def test_auto_open_setting_off_keeps_review_closed_while_staging(qapp, tmp_path: Path):
    window = _window(tmp_path)
    window._handle_setting_change("auto_open_review_drawer", False)

    window.action_cards["disable_telemetry"].set_target_state(True)

    assert window.review_drawer.isVisible() is False
    assert window.review_launcher.property("pending") is True


def test_removing_a_staged_row_from_review_unstages_it(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)
    window.action_cards["disable_telemetry"].set_target_state(True)
    window.action_cards["disable_cortana"].set_target_state(True)
    assert window.review_drawer.staged_list.count() == 2

    window.review_drawer._remove_action("disable_telemetry")

    assert "disable_telemetry" not in controller.staged_targets
    assert window.review_drawer.staged_list.count() == 1
    assert window.action_cards["disable_telemetry"].changed_chip.isHidden() is True


def test_startup_entry_toggle_stages_without_mutating_machine(qapp, tmp_path: Path):
    platform = InMemoryPlatformFacade()
    controller = build_controller(tmp_path, platform=platform)
    window = TweakifyMainWindow(controller)

    entry = controller.startup_inventory["items"][0]
    window.startup_entries_panel.entry_cards[entry.id].set_target_state(False)

    assert controller.staged_startup_entries[entry.id] is False
    assert "1 pending" in window.review_tray.summary_label.text().lower()
    refreshed = next(item for item in platform.startup_inventory()["items"] if item.id == entry.id)
    assert refreshed.enabled is True


def test_blocked_actions_show_why_not_explanations(qapp, tmp_path: Path):
    window = _window(tmp_path)

    text = window.compatibility_page.blocked_list.toPlainText()
    assert "nvidiaProfileInspector.exe" in text
    assert "unavailable in this build" not in text.lower()
    assert "legacy" not in text.lower()
    assert window.compatibility_page.list_layout.count() >= 1


def test_live_enabled_action_is_not_marked_as_pending(qapp, tmp_path: Path):
    platform = InMemoryPlatformFacade()
    platform.registry_set(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry", 0)
    window = TweakifyMainWindow(build_controller(tmp_path, platform=platform))

    row = window.action_cards["disable_telemetry"]
    assert row.current_state_chip.text() == "On"
    assert row.toggle.text() == "On"
    assert row.toggle.isChecked() is True
    assert row.changed_chip.isHidden() is True


def test_tweak_rows_use_animated_switches_and_run_buttons(qapp, tmp_path: Path):
    window = _window(tmp_path)

    assert isinstance(window.action_cards["disable_telemetry"].toggle, ToggleSwitch)
    assert window.action_cards["disable_telemetry"].toggle.isCheckable() is True
    assert window.action_cards["empty_recycle_bin"].toggle.isCheckable() is False


def test_run_button_toggles_a_maintenance_task_in_and_out_of_the_plan(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)
    row = window.action_cards["empty_recycle_bin"]

    row.toggle.click()
    assert controller.staged_targets == {"empty_recycle_bin": True}
    assert row.toggle.text() == "Queued"

    row.toggle.click()
    assert controller.staged_targets == {}
    assert row.toggle.text() == "Run"


def test_staging_toggle_does_not_trigger_full_refresh(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    def fail():
        raise AssertionError("staging must not re-probe the machine")

    controller.refresh_machine_context = fail
    controller.refresh_diagnostics = fail
    window.action_cards["disable_telemetry"].set_target_state(True)

    assert controller.staged_targets == {"disable_telemetry": True}


def test_row_refresh_skips_work_when_nothing_changed(qapp, tmp_path: Path):
    window = _window(tmp_path)
    row = window.action_cards["disable_telemetry"]
    calls = []
    original = row.toggle.setChecked
    row.toggle.setChecked = lambda value: (calls.append(value), original(value))

    row.refresh()
    row.refresh()

    assert calls == []


def test_module_filter_shows_only_pending_rows(qapp, tmp_path: Path):
    window = _window(tmp_path)
    page = window.module_pages["privacy"]
    window.action_cards["disable_telemetry"].set_target_state(True)

    page.set_filter("pending")

    visible = [row.action.definition.id for group in page.groups for row in group.rows if not row.isHidden()]
    assert visible == ["disable_telemetry"]
    assert page.empty_state.isHidden() is True

    window.review_drawer.clear()
    page.apply_filter()
    assert page.empty_state.isHidden() is False


def test_enable_recommended_stages_only_safe_settings_that_are_off(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    window._stage_module_recommended("privacy")

    assert controller.staged_targets
    for action_id in controller.staged_targets:
        definition = controller.actions_by_id[action_id].definition
        assert definition.module_id == "privacy"
        assert definition.safety_tier.value == "Safe"
        assert definition.kind.value == "setting"


def test_runtime_refresh_reuses_rows_when_the_catalog_is_unchanged(qapp, tmp_path: Path):
    window = _window(tmp_path)
    before = window.action_cards["disable_telemetry"]

    window._populate_module_pages()

    assert window.action_cards["disable_telemetry"] is before


def test_safety_filter_change_rebuilds_rows(qapp, tmp_path: Path):
    window = _window(tmp_path)
    assert "disable_cpu_core_parking" in window.action_cards

    window._handle_setting_change("show_advanced", False)

    assert "disable_cpu_core_parking" not in window.action_cards


def test_command_palette_finds_tweaks_and_reveals_them(qapp, tmp_path: Path):
    window = _window(tmp_path)

    window.command_palette.open()
    window.command_palette.input.setText("cloudflare")
    titles = [entry.title for entry in window.command_palette.visible_entries]
    assert titles[0] == "Use Cloudflare DNS"

    window.command_palette._activate()

    assert window.command_palette.isHidden()
    assert window.stack.currentIndex() == _page_index("network")
    assert window.action_cards["dns_cloudflare"].property("flash") is True


def test_command_palette_runs_commands(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    window.command_palette.open()
    window.command_palette.input.setText("optimize now")
    window.command_palette._activate()

    assert controller.staged_targets


def test_live_monitor_feeds_tiles_and_top_bar(qapp, tmp_path: Path):
    window = _window(tmp_path)
    window._live_sampler = window.controller.platform.create_live_sampler()

    for _ in range(5):
        window._sample_live()

    assert "CPU" in window.live_readout.text()
    assert window.dashboard_page.cpu_tile.value_label.text() != "--"
    assert len(window.dashboard_page.memory_tile.sparkline.values) == 5
    assert "GB" in window.dashboard_page.memory_tile.detail_label.text()


def test_free_memory_quick_action_reports_result(qapp, tmp_path: Path):
    window = _window(tmp_path, is_admin=True)
    window.refresh_coordinator.request = lambda domain, fn: window._handle_background_result(domain, fn())

    window.dashboard_page.free_ram_button.click()

    assert "emptied" in window.dashboard_page.free_ram_button.caption_label.text().lower()
    assert "purge-standby-list" in window.controller.platform.command_log


def test_public_copy_omits_internal_recovery_language(qapp, tmp_path: Path):
    window = _window(tmp_path)
    for text in (window.sidebar_subtitle.text(), window.dashboard_page.caption_label.text()):
        assert "legacy" not in text.lower()
        assert "batch" not in text.lower()


def test_settings_page_renders_public_setting_groups(qapp, tmp_path: Path):
    window = _window(tmp_path)

    assert set(window.settings_page.group_cards) == {"Appearance", "Behavior", "Diagnostics", "Integrations", "Games", "Safety"}
    assert {"theme_mode", "accent_color", "review_tray_open", "auto_open_review_drawer"} <= set(window.settings_page.controls)
    assert window.settings_page.nvidia_dependency_card is not None


def test_accent_color_change_restyles_without_machine_refresh(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    def fail():
        raise AssertionError("appearance changes must not re-probe the machine")

    controller.refresh_machine_context = fail
    window.settings_page.accent_buttons["azure"].click()

    assert controller.settings.accent_color == "azure"
    assert "#5B9BFF" in window.styleSheet()
    assert window.settings_page.accent_buttons["azure"].isChecked()


def test_interactive_controls_use_pointing_hand_cursor(qapp, tmp_path: Path):
    window = _window(tmp_path)

    assert window.sidebar_buttons[0].cursor().shape() == Qt.PointingHandCursor
    assert window.action_cards["disable_telemetry"].toggle.cursor().shape() == Qt.PointingHandCursor
    assert window.review_drawer.apply_button.cursor().shape() == Qt.PointingHandCursor
    assert window.search_launcher.cursor().shape() == Qt.PointingHandCursor


def test_apply_history_and_rollback_render_snapshot_state(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade(is_admin=True))
    window = TweakifyMainWindow(controller)
    window.action_cards["disable_telemetry"].set_target_state(True)

    transaction = controller.apply_staged()
    window.refresh_all()

    assert transaction.results
    assert window.snapshots_page.snapshot_list.count() >= 1
    assert controller.rollback_snapshot(controller.store.list_snapshots()[0].snapshot_id).results


def test_settings_appearance_change_does_not_trigger_machine_or_diagnostics_refresh(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    def fail():
        raise AssertionError("appearance changes must not re-probe the machine")

    controller.refresh_machine_context = fail
    controller.refresh_diagnostics = fail
    window._handle_setting_change("compact_mode", True)

    assert controller.settings.compact_mode is True


def test_apply_updates_result_text_and_clears_the_plan(qapp, tmp_path: Path):
    window = _window(tmp_path, is_admin=True)
    window._handle_setting_change("confirm_before_apply", False)
    window.action_cards["disable_telemetry"].set_target_state(True)
    window._handle_setting_change("review_tray_open", True)

    window.refresh_coordinator.request = lambda domain, fn: window._handle_background_result(domain, fn())
    window.review_drawer.apply()

    assert window.review_drawer.isVisible() is True
    assert window.review_drawer.staged_list.count() == 0
    assert "applied" in window.review_drawer.plan_text.toPlainText().lower()
    assert "no pending changes" in window.review_drawer.summary_label.text().lower()
    assert window.toast.isVisible() is True


def test_apply_animates_review_text_while_background_apply_is_pending(qapp, tmp_path: Path):
    window = _window(tmp_path, is_admin=True)
    window._handle_setting_change("confirm_before_apply", False)
    window.action_cards["disable_telemetry"].set_target_state(True)
    window.refresh_coordinator.request = lambda domain, fn: None

    window.review_drawer.apply()
    frames = [window.review_drawer.plan_text.toPlainText()]
    for _ in range(2):
        window.review_drawer._advance_apply_animation()
        frames.append(window.review_drawer.plan_text.toPlainText())

    assert window.review_drawer._apply_animation_timer.isActive() is True
    assert frames == ["Applying staged changes.", "Applying staged changes..", "Applying staged changes..."]
    assert window.review_drawer.apply_button.isEnabled() is False

    window.review_drawer.show_error("cancelled")
    assert window.review_drawer._apply_animation_timer.isActive() is False


def test_theme_mode_switches_resolved_theme_without_full_refresh(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    def fail():
        raise AssertionError("theme changes must not re-probe the machine")

    controller.refresh_machine_context = fail
    window._handle_setting_change("theme_mode", "light")
    assert window.resolved_theme_mode == "light"
    window.theme_button.click()
    assert window.resolved_theme_mode == "dark"


def test_window_stylesheet_and_scroll_policies(qapp, tmp_path: Path):
    window = _window(tmp_path)

    sheet = window.styleSheet()
    assert "QScrollBar:vertical" in sheet
    assert "QScrollBar::handle:vertical" in sheet
    for page in (
        window.dashboard_page, window.presets_page, window.module_pages["performance"],
        window.compatibility_page, window.restore_page, window.settings_page,
    ):
        assert page.scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert window.startup_page.column_layout.itemAt(0).widget() is window.startup_page.header_card
    assert window.startup_page.column_layout.itemAt(1).widget() is window.startup_page.tabs


def test_startup_page_uses_apps_and_tweaks_tabs_with_scroll_areas(qapp, tmp_path: Path):
    window = _window(tmp_path)

    assert window.startup_page.tabs.tabText(0) == "Startup Apps"
    assert window.startup_page.tabs.tabText(1) == "Startup Tweaks"
    assert window.startup_page.apps_scroll.objectName() == "startupAppsScroll"
    assert window.startup_page.tweaks_scroll.objectName() == "startupTweaksScroll"
    assert window.startup_page.apps_scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn


def test_startup_entries_panel_renders_inventory_cards(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    assert set(window.startup_entries_panel.entry_cards) == {item.id for item in controller.startup_inventory["items"]}


def test_startup_tabs_keep_cards_content_sized(qapp, tmp_path: Path):
    window = _window(tmp_path)
    window.resize(1360, 900)
    window._set_page(_page_index("startup"))
    qapp.processEvents()

    window.startup_page.tabs.setCurrentIndex(window.startup_page.APPS_TAB)
    qapp.processEvents()
    assert window.startup_entries_panel.height() <= window.startup_entries_panel.sizeHint().height() + 8

    window.startup_page.tabs.setCurrentIndex(window.startup_page.TWEAKS_TAB)
    qapp.processEvents()
    first_group = window.startup_page.tweaks_layout.itemAt(0).widget()
    assert first_group.height() <= first_group.sizeHint().height() + 8


def _with_extra_startup_entries(prefix: str) -> InMemoryPlatformFacade:
    platform = InMemoryPlatformFacade()
    for index in range(18):
        platform.startup_entries.append(
            {
                "id": f"run:{prefix}:{index}",
                "name": f"{prefix.title()} {index:02d}",
                "location": "Run",
                "enabled": True,
                "command": f"{prefix}{index}.exe",
                "source_kind": "registry",
                "scope": "user",
                "registry_path": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                "value_name": f"{prefix.title()}{index:02d}",
            }
        )
    return platform


def test_startup_toggle_preserves_apps_scroll_position(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=_with_extra_startup_entries("extra"))
    window = TweakifyMainWindow(controller)
    window.resize(1280, 820)
    window._set_page(_page_index("startup"))
    window.startup_page.tabs.setCurrentIndex(window.startup_page.APPS_TAB)
    qapp.processEvents()

    scrollbar = window.startup_page.apps_scroll.verticalScrollBar()
    scrollbar.setValue(max(40, scrollbar.maximum() // 2))
    original = scrollbar.value()
    last = controller.startup_inventory["items"][-1]
    window.startup_entries_panel.entry_cards[last.id].set_target_state(False)
    qapp.processEvents()

    assert window.startup_page.apps_scroll.verticalScrollBar().value() >= max(1, original - 8)


def test_startup_full_refresh_preserves_tab_index_and_scroll_offsets(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=_with_extra_startup_entries("refresh"))
    window = TweakifyMainWindow(controller)
    window.resize(1280, 820)
    window._set_page(_page_index("startup"))
    apps_bar = window.startup_page.apps_scroll.verticalScrollBar()
    window.startup_page.tabs.setCurrentIndex(window.startup_page.APPS_TAB)
    apps_bar.setValue(max(40, apps_bar.maximum() // 2))
    apps_value = apps_bar.value()
    qapp.processEvents()

    window.startup_page.tabs.setCurrentIndex(window.startup_page.TWEAKS_TAB)
    window.refresh_all()
    qapp.processEvents()

    assert window.startup_page.tabs.requested_index == window.startup_page.TWEAKS_TAB
    assert window.startup_page._saved_state["apps_scroll"] >= max(1, apps_value - 8)


def test_apply_clears_review_items_when_plan_requests_elevation(qapp, tmp_path: Path):
    window = _window(tmp_path, is_admin=False)
    window._handle_setting_change("confirm_before_apply", False)
    window.action_cards["disable_telemetry"].set_target_state(True)

    window.refresh_coordinator.request = lambda domain, fn: window._handle_background_result(domain, fn())
    window.review_drawer.apply()

    assert window.review_drawer.staged_list.count() == 0
    assert "no pending changes" in window.review_drawer.summary_label.text().lower()


def test_settings_cards_stay_content_sized_in_compact_mode(qapp, tmp_path: Path):
    window = _window(tmp_path)
    window.resize(1360, 900)
    window._set_page(_page_index("settings"))
    qapp.processEvents()

    window._handle_setting_change("compact_mode", True)
    qapp.processEvents()

    for name in ("Appearance", "Behavior"):
        card = window.settings_page.group_cards[name]
        assert card.height() <= card.sizeHint().height() + 8


def test_staging_preset_updates_card_feedback_immediately(qapp, tmp_path: Path):
    window = _window(tmp_path)

    window.presets_page._stage("gaming")

    card = window.presets_page.card_views["gaming"]
    assert "will add" in card.primary_label.text().lower()
    assert "added" in card.result_label.text().lower()


def test_preset_cards_are_reused_across_refreshes(qapp, tmp_path: Path):
    window = _window(tmp_path)
    before = window.presets_page.card_views["gaming"]

    window.presets_page.refresh()

    assert window.presets_page.card_views["gaming"] is before


def test_baseline_restore_surfaces_already_at_baseline_in_review(qapp, tmp_path: Path):
    window = _window(tmp_path)

    window.presets_page._stage("baseline_restore")

    assert "already at baseline" in window.review_drawer.plan_text.toPlainText().lower()
    assert "no pending changes" in window.review_drawer.summary_label.text().lower()
