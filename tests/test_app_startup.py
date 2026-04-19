from pathlib import Path

from app.controller import TweakifyController
from app.platform.adapters import InMemoryPlatformFacade
from app.ui.main_window import TweakifyMainWindow


def test_light_startup_window_disables_controls_and_requests_background_refresh(monkeypatch, qapp, qtbot, tmp_path: Path):
    requests: list[tuple[str, object]] = []
    monkeypatch.setattr(
        "app.ui.main_window.RefreshCoordinator.request",
        lambda self, domain, fn: requests.append((domain, fn)),
    )

    controller = TweakifyController(
        platform=InMemoryPlatformFacade(),
        storage_root=tmp_path,
        startup_profile="light",
    )
    window = TweakifyMainWindow(controller)

    qtbot.waitUntil(lambda: any(domain == "runtime" for domain, _fn in requests), timeout=5000)

    card = window.action_cards["disable_telemetry"]

    assert card.toggle.isEnabled() is False
    assert card.current_state_chip.text() == "Loading"
    assert "loading" in window.dashboard_page.summary_caption.text().lower()
    assert "loading" in window.startup_entries_panel.summary_label.text().lower()

    window.close()


def test_runtime_snapshot_result_unlocks_controls_and_queues_baseline_capture(monkeypatch, qapp, qtbot, tmp_path: Path):
    requests: list[tuple[str, object]] = []
    monkeypatch.setattr(
        "app.ui.main_window.RefreshCoordinator.request",
        lambda self, domain, fn: requests.append((domain, fn)),
    )

    controller = TweakifyController(
        platform=InMemoryPlatformFacade(),
        storage_root=tmp_path,
        startup_profile="light",
    )
    window = TweakifyMainWindow(controller)
    qtbot.waitUntil(lambda: any(domain == "runtime" for domain, _fn in requests), timeout=5000)
    requests.clear()

    window._handle_background_result("runtime", controller.build_runtime_snapshot(force_live_diagnostics=True))

    card = window.action_cards["disable_telemetry"]

    assert controller.runtime_pending is False
    assert card.toggle.isEnabled() is True
    assert card.current_state_chip.text() in {"On", "Off"}
    assert window.startup_entries_panel.entry_cards
    assert any(domain == "baseline" for domain, _fn in requests)

    window.close()
