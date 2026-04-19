from __future__ import annotations

from app.actions import cleanup, graphics, input_ui, network, performance, restore, services, startup


def build_action_catalog(platform) -> list:
    catalog = []
    for builder in (
        startup.build_actions,
        performance.build_actions,
        network.build_actions,
        services.build_actions,
        cleanup.build_actions,
        input_ui.build_actions,
        graphics.build_actions,
        restore.build_actions,
    ):
        catalog.extend(builder(platform))
    return catalog
