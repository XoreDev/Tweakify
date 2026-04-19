from pathlib import Path

from PySide6.QtCore import Qt

from app.platform.adapters import InMemoryPlatformFacade
from app.ui.main_window import TweakifyMainWindow
from tests.conftest import build_controller


def test_dashboard_surfaces_admin_privilege_note(qapp, tmp_path: Path):
    window = TweakifyMainWindow(build_controller(tmp_path, platform=InMemoryPlatformFacade()))

    assert (
        "administrator privileges"
        in window.dashboard_page.admin_notice_label.text().lower()
    )


def test_main_window_renders_sidebar_and_dashboard(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    sidebar_labels = [button.text() for button in window.sidebar_buttons]
    assert sidebar_labels == [
        "Dashboard",
        "Presets",
        "Startup",
        "Performance",
        "Network",
        "Services",
        "Cleanup",
        "Input + UI",
        "Graphics",
        "Compatibility",
        "Restore",
        "Settings",
    ]
    assert window.dashboard_page.title_label.text() == "Dashboard"
    assert window.dashboard_page.metrics_layout.count() >= 5
    assert window.dashboard_page.scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert window.review_drawer.isVisible() is True
    assert not hasattr(window, "review_drawer_toggle")


def test_staging_updates_review_tray_without_mutating_machine(qapp, tmp_path: Path):
    platform = InMemoryPlatformFacade()
    controller = build_controller(tmp_path, platform=platform)
    window = TweakifyMainWindow(controller)

    card = window.action_cards["disable_telemetry"]
    card.set_target_state(True)

    assert controller.staged_targets["disable_telemetry"] is True
    assert "1 pending" in window.review_tray.summary_label.text().lower()
    assert platform.registry_get(
        r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection",
        "AllowTelemetry",
    ) is None


def test_startup_entry_toggle_stages_without_mutating_machine(qapp, tmp_path: Path):
    platform = InMemoryPlatformFacade()
    controller = build_controller(tmp_path, platform=platform)
    window = TweakifyMainWindow(controller)

    entry = controller.startup_inventory["items"][0]
    card = window.startup_entries_panel.entry_cards[entry.id]
    card.set_target_state(False)

    assert controller.staged_startup_entries[entry.id] is False
    assert "1 pending" in window.review_tray.summary_label.text().lower()
    refreshed = next(item for item in platform.startup_inventory()["items"] if item.id == entry.id)
    assert refreshed.enabled is True


def test_blocked_actions_show_why_not_explanations(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    text = window.compatibility_page.blocked_list.toPlainText()
    assert "nvidiaInspector.exe" in text
    assert "unavailable in this build" not in text.lower()
    assert "legacy" not in text.lower()
    assert "batch" not in text.lower()


def test_live_enabled_action_is_not_marked_as_pending(qapp, tmp_path: Path):
    platform = InMemoryPlatformFacade()
    platform.registry_set(
        r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection",
        "AllowTelemetry",
        0,
    )
    controller = build_controller(tmp_path, platform=platform)
    window = TweakifyMainWindow(controller)

    card = window.action_cards["disable_telemetry"]
    assert card.current_state_chip.text() == "On"
    assert card.toggle.text() == "On"
    assert card.changed_chip.isHidden() is True


def test_staging_toggle_does_not_trigger_full_refresh(qapp, tmp_path: Path):
    platform = InMemoryPlatformFacade()
    controller = build_controller(tmp_path, platform=platform)
    window = TweakifyMainWindow(controller)

    def fail_machine_context():
        raise AssertionError("staging should not refresh machine context")

    def fail_diagnostics():
        raise AssertionError("staging should not refresh diagnostics")

    controller.refresh_machine_context = fail_machine_context
    controller.refresh_diagnostics = fail_diagnostics

    window.action_cards["disable_telemetry"].set_target_state(True)

    assert controller.staged_targets == {"disable_telemetry": True}


def test_public_copy_omits_internal_recovery_language(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    assert "legacy" not in window.sidebar_subtitle.text().lower()
    assert "batch" not in window.sidebar_subtitle.text().lower()
    assert "legacy" not in window.dashboard_page.caption_label.text().lower()
    assert "batch" not in window.dashboard_page.caption_label.text().lower()


def test_settings_page_renders_public_setting_groups(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    assert set(window.settings_page.group_cards) == {
        "Appearance",
        "Behavior",
        "Diagnostics",
        "Integrations",
        "Safety",
    }
    assert "theme_mode" in window.settings_page.controls
    assert window.settings_page.nvidia_dependency_card is not None


def test_interactive_controls_use_pointing_hand_cursor(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    assert window.sidebar_buttons[0].cursor().shape() == Qt.PointingHandCursor
    assert window.action_cards["disable_telemetry"].toggle.cursor().shape() == Qt.PointingHandCursor
    assert window.review_drawer.apply_button.cursor().shape() == Qt.PointingHandCursor


def test_maintenance_actions_render_with_non_toggle_primary_button(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    assert window.action_cards["disable_telemetry"].toggle.isCheckable() is True
    assert window.action_cards["empty_recycle_bin"].toggle.isCheckable() is False


def test_apply_history_and_rollback_render_snapshot_state(qapp, tmp_path: Path):
    platform = InMemoryPlatformFacade(is_admin=True)
    controller = build_controller(tmp_path, platform=platform)
    window = TweakifyMainWindow(controller)
    window.action_cards["disable_telemetry"].set_target_state(True)

    transaction = controller.apply_staged()
    window.refresh_all()

    assert transaction.results
    assert window.snapshots_page.snapshot_list.count() >= 1

    latest_snapshot = controller.store.list_snapshots()[0]
    rollback = controller.rollback_snapshot(latest_snapshot.snapshot_id)
    assert rollback.results


def test_settings_appearance_change_does_not_trigger_machine_or_diagnostics_refresh(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    def fail_machine_context():
        raise AssertionError("appearance changes should not refresh machine context")

    def fail_diagnostics():
        raise AssertionError("appearance changes should not refresh diagnostics")

    controller.refresh_machine_context = fail_machine_context
    controller.refresh_diagnostics = fail_diagnostics

    window._handle_setting_change("compact_mode", True)

    assert controller.settings.compact_mode is True


def test_review_panel_stays_visible_on_startup_and_after_discard(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    assert window.review_drawer.isVisible() is True

    window.action_cards["disable_telemetry"].set_target_state(True)
    window.review_drawer.clear()

    assert window.review_drawer.isVisible() is True
    assert "discarded" in window.review_drawer.plan_text.toPlainText().lower()


def test_review_panel_visibility_tracks_settings_without_sidebar_toggle(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    assert "review_tray_open" in window.settings_page.controls

    window._handle_setting_change("review_tray_open", False)
    assert window.review_drawer.isVisible() is False

    window._handle_setting_change("review_tray_open", True)
    assert window.review_drawer.isVisible() is True
    assert not hasattr(window, "review_drawer_toggle")


def test_apply_keeps_review_panel_open_and_updates_result_text(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade(is_admin=True))
    window = TweakifyMainWindow(controller)
    window._handle_setting_change("confirm_before_apply", False)
    window.action_cards["disable_telemetry"].set_target_state(True)

    window.refresh_coordinator.request = lambda domain, fn: window._handle_background_result(domain, fn())
    window.review_drawer.apply()

    assert window.review_drawer.isVisible() is True
    assert window.review_drawer.staged_list.count() == 0
    assert "applied" in window.review_drawer.plan_text.toPlainText().lower() or "disabled telemetry" in window.review_drawer.plan_text.toPlainText().lower()
    assert "no pending changes" in window.review_drawer.summary_label.text().lower()


def test_apply_animates_review_text_while_background_apply_is_pending(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade(is_admin=True))
    window = TweakifyMainWindow(controller)
    window._handle_setting_change("confirm_before_apply", False)
    window.action_cards["disable_telemetry"].set_target_state(True)
    window.refresh_coordinator.request = lambda domain, fn: None

    window.review_drawer.apply()
    first = window.review_drawer.plan_text.toPlainText()
    window.review_drawer._advance_apply_animation()
    second = window.review_drawer.plan_text.toPlainText()
    window.review_drawer._advance_apply_animation()
    third = window.review_drawer.plan_text.toPlainText()

    assert window.review_drawer._apply_animation_timer.isActive() is True
    assert first == "Applying staged changes."
    assert second == "Applying staged changes.."
    assert third == "Applying staged changes..."

    window.review_drawer.show_error("cancelled")
    assert window.review_drawer._apply_animation_timer.isActive() is False


def test_theme_mode_switches_resolved_theme_without_full_refresh(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    def fail_machine_context():
        raise AssertionError("theme changes should not refresh machine context")

    controller.refresh_machine_context = fail_machine_context
    window._handle_setting_change("theme_mode", "light")
    assert window.resolved_theme_mode == "light"

    window._handle_setting_change("theme_mode", "dark")
    assert window.resolved_theme_mode == "dark"


def test_window_stylesheet_contains_simplified_scrollbar_rules(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    assert "QScrollBar:vertical" in window.styleSheet()
    assert "QScrollBar::handle:vertical" in window.styleSheet()
    assert "border-radius: 7px" in window.styleSheet()
    assert window.dashboard_page.scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert window.presets_page.scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert window.module_pages["performance"].scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert window.compatibility_page.scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert window.restore_page.scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert window.settings_page.scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert window.startup_page.layout().itemAt(0).widget() is window.startup_page.header_card
    assert window.startup_page.layout().itemAt(1).widget() is window.startup_page.tabs
    assert window.startup_page.tweaks_scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert window.startup_page.apps_scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn


def test_startup_page_uses_apps_and_tweaks_tabs_with_scroll_areas(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    assert window.startup_page.tabs.tabText(0) == "Startup Tweaks"
    assert window.startup_page.tabs.tabText(1) == "Startup Apps"
    assert window.startup_page.tweaks_scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert window.startup_page.apps_scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert window.startup_page.tweaks_scroll.objectName() == "startupTweaksScroll"
    assert window.startup_page.apps_scroll.objectName() == "startupAppsScroll"


def test_startup_entries_panel_renders_inventory_cards(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    assert window.startup_entries_panel is not None
    assert set(window.startup_entries_panel.entry_cards) == {
        item.id for item in controller.startup_inventory["items"]
    }


def test_startup_tabs_keep_cards_content_sized_and_scrollable(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)
    window.resize(1360, 900)
    window._set_page(2)
    qapp.processEvents()

    window.startup_page.tabs.setCurrentIndex(1)
    qapp.processEvents()
    assert window.startup_entries_panel.height() <= window.startup_entries_panel.sizeHint().height() + 8

    window.startup_page.tabs.setCurrentIndex(0)
    qapp.processEvents()
    first_group = next(
        item.widget()
        for item_index in range(window.startup_page.tweaks_layout.count())
        if (item := window.startup_page.tweaks_layout.itemAt(item_index)).widget() is not None
    )
    assert first_group.height() <= first_group.sizeHint().height() + 8


def test_startup_toggle_preserves_apps_scroll_position(qapp, tmp_path: Path):
    platform = InMemoryPlatformFacade()
    for index in range(18):
        platform.startup_entries.append(
            {
                "id": f"run:extra:{index}",
                "name": f"Extra {index:02d}",
                "location": "Run",
                "enabled": True,
                "command": f"extra{index}.exe",
                "source_kind": "registry",
                "scope": "user",
                "registry_path": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                "value_name": f"Extra{index:02d}",
            }
        )
    controller = build_controller(tmp_path, platform=platform)
    window = TweakifyMainWindow(controller)
    window.resize(1280, 820)
    window._set_page(2)
    window.startup_page.tabs.setCurrentIndex(1)
    qapp.processEvents()

    scrollbar = window.startup_page.apps_scroll.verticalScrollBar()
    scrollbar.setValue(max(40, scrollbar.maximum() // 2))
    original_value = scrollbar.value()
    last_entry = controller.startup_inventory["items"][-1]

    window.startup_entries_panel.entry_cards[last_entry.id].set_target_state(False)
    qapp.processEvents()

    assert window.startup_page.apps_scroll.verticalScrollBar().value() >= max(1, original_value - 8)


def test_startup_full_refresh_preserves_tab_index_and_scroll_offsets(qapp, tmp_path: Path):
    platform = InMemoryPlatformFacade()
    for index in range(18):
        platform.startup_entries.append(
            {
                "id": f"run:refresh:{index}",
                "name": f"Refresh {index:02d}",
                "location": "Run",
                "enabled": True,
                "command": f"refresh{index}.exe",
                "source_kind": "registry",
                "scope": "user",
                "registry_path": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                "value_name": f"Refresh{index:02d}",
            }
        )
    controller = build_controller(tmp_path, platform=platform)
    window = TweakifyMainWindow(controller)
    window.resize(1280, 820)
    window._set_page(2)
    apps_bar = window.startup_page.apps_scroll.verticalScrollBar()
    window.startup_page.tabs.setCurrentIndex(1)
    apps_bar.setValue(max(40, apps_bar.maximum() // 2))
    apps_value = apps_bar.value()
    qapp.processEvents()

    window.refresh_all()
    window.startup_page.tabs.setCurrentIndex(1)
    qapp.processEvents()

    assert window.startup_page.tabs.requested_index == 1
    assert window.startup_page._saved_state is not None
    assert window.startup_page._saved_state["apps_scroll"] >= max(1, apps_value - 8)


def test_apply_clears_review_items_when_plan_requests_elevation(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade(is_admin=False))
    window = TweakifyMainWindow(controller)
    window._handle_setting_change("confirm_before_apply", False)
    window.action_cards["disable_telemetry"].set_target_state(True)

    window.refresh_coordinator.request = lambda domain, fn: window._handle_background_result(domain, fn())
    window.review_drawer.apply()

    assert window.review_drawer.isVisible() is True
    assert window.review_drawer.staged_list.count() == 0
    assert "no pending changes" in window.review_drawer.summary_label.text().lower()


def test_settings_compact_mode_keeps_cards_top_aligned(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)
    window.resize(1360, 900)
    window._set_page(11)
    qapp.processEvents()

    window._handle_setting_change("compact_mode", True)
    qapp.processEvents()

    appearance = window.settings_page.group_cards["Appearance"]
    behavior = window.settings_page.group_cards["Behavior"]
    viewport_height = window.settings_page.scroll.viewport().height()

    assert appearance.height() < int(viewport_height * 0.75)
    assert behavior.height() < int(viewport_height * 0.75)


def test_staging_preset_updates_card_feedback_immediately(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    window.presets_page._stage("gaming")

    card = window.presets_page.card_views["gaming"]
    assert "will add" in card.primary_label.text().lower()
    assert "added" in card.result_label.text().lower()


def test_baseline_restore_surfaces_already_at_baseline_in_review(qapp, tmp_path: Path):
    controller = build_controller(tmp_path, platform=InMemoryPlatformFacade())
    window = TweakifyMainWindow(controller)

    window.presets_page._stage("baseline_restore")

    assert "already at baseline" in window.review_drawer.plan_text.toPlainText().lower()
    assert "no pending changes" in window.review_drawer.summary_label.text().lower()

