from __future__ import annotations

from app.domain.models import PresetDefinition, SafetyTier


def build_presets(actions, baseline_targets: dict[str, bool] | None = None) -> list[PresetDefinition]:
    action_map = {action.definition.id: action for action in actions}
    safe_ids = {
        action.definition.id
        for action in actions
        if action.definition.safety_tier == SafetyTier.SAFE
    }
    baseline_targets = baseline_targets or {}

    def keep_known(targets: dict[str, bool]) -> dict[str, bool]:
        return {key: value for key, value in targets.items() if key in action_map}

    def safe_bundle(action_ids: list[str]) -> dict[str, bool]:
        return {
            action_id: True
            for action_id in action_ids
            if action_id in action_map and action_id in safe_ids
        }

    presets = [
        PresetDefinition(
            id="baseline_restore",
            title="Baseline Restore",
            description="Return every reversible public action to the captured baseline state.",
            accent="#8a5cff",
            action_targets=keep_known(baseline_targets),
        ),
        PresetDefinition(
            id="gaming",
            title="Gaming",
            description="Packed gaming-first preset with shell clutter reduced, startup trimmed, graphics preferences tightened, and safe maintenance staged for the next apply.",
            accent="#9d6bff",
            action_targets=safe_bundle(
                [
                    "disable_startup_delay",
                    "disable_browser_background_mode",
                    "disable_edge_startup_boost",
                    "disable_telemetry_tasks",
                    "disable_ceip_tasks",
                    "disable_onedrive_startup",
                    "high_performance_power_plan",
                    "adjust_visual_effects",
                    "disable_game_mode",
                    "disable_llmnr",
                    "disable_telemetry",
                    "disable_background_apps",
                    "disable_cortana",
                    "disable_notifications",
                    "disk_cleanup",
                    "clear_temp_files",
                    "optimize_defrag_drives",
                    "check_disk_errors",
                    "remove_shortcut_text",
                    "disable_enhance_pointer_precision",
                    "adjust_mouse_trails",
                    "optimize_mouse_double_click",
                    "optimize_key_repeat_delay",
                    "disable_recent_files",
                    "disable_widgets",
                    "disable_animations",
                    "disable_aero_peak",
                    "disable_balloon_tips",
                    "improve_menu_speed",
                    "disable_game_dvr",
                    "set_highest_refresh_rate",
                ]
            ),
        ),
        PresetDefinition(
            id="low_latency",
            title="Low Latency",
            description="Input- and responsiveness-focused preset that keeps the shell lean, trims background extras, and stages the safer latency-oriented controls.",
            accent="#b178ff",
            action_targets=safe_bundle(
                [
                    "disable_startup_delay",
                    "disable_browser_background_mode",
                    "disable_edge_startup_boost",
                    "disable_telemetry_tasks",
                    "disable_ceip_tasks",
                    "high_performance_power_plan",
                    "adjust_visual_effects",
                    "disable_game_mode",
                    "disable_llmnr",
                    "disable_telemetry",
                    "disable_background_apps",
                    "disable_notifications",
                    "disable_enhance_pointer_precision",
                    "adjust_mouse_trails",
                    "optimize_mouse_double_click",
                    "optimize_key_repeat_delay",
                    "disable_recent_files",
                    "disable_widgets",
                    "disable_animations",
                    "disable_aero_peak",
                    "disable_balloon_tips",
                    "improve_menu_speed",
                    "disable_game_dvr",
                    "set_highest_refresh_rate",
                ]
            ),
        ),
        PresetDefinition(
            id="balanced",
            title="Balanced",
            description="High-value safe cleanup and responsiveness preset for daily use without leaning hard into niche or security-sensitive tweaks.",
            accent="#a46dff",
            action_targets=safe_bundle(
                [
                    "disable_startup_delay",
                    "disable_browser_background_mode",
                    "disable_edge_startup_boost",
                    "disable_telemetry_tasks",
                    "disable_ceip_tasks",
                    "disable_onedrive_startup",
                    "adjust_visual_effects",
                    "disable_game_mode",
                    "disable_llmnr",
                    "disable_telemetry",
                    "disable_background_apps",
                    "disable_notifications",
                    "disk_cleanup",
                    "clear_temp_files",
                    "optimize_defrag_drives",
                    "check_disk_errors",
                    "remove_shortcut_text",
                    "disable_enhance_pointer_precision",
                    "optimize_mouse_double_click",
                    "optimize_key_repeat_delay",
                    "disable_recent_files",
                    "disable_widgets",
                    "disable_animations",
                    "disable_aero_peak",
                    "disable_balloon_tips",
                    "improve_menu_speed",
                    "disable_game_dvr",
                ]
            ),
        ),
        PresetDefinition(
            id="privacy_minimal",
            title="Privacy Minimal",
            description="Safe-heavy preset focused on obvious telemetry, recommendations, startup extras, and shell noise without crossing into security-off behavior.",
            accent="#d27bff",
            action_targets=safe_bundle(
                [
                    "disable_startup_delay",
                    "disable_browser_background_mode",
                    "disable_edge_startup_boost",
                    "disable_telemetry_tasks",
                    "disable_ceip_tasks",
                    "disable_onedrive_startup",
                    "adjust_visual_effects",
                    "disable_llmnr",
                    "disable_telemetry",
                    "disable_background_apps",
                    "disable_cortana",
                    "disable_notifications",
                    "disk_cleanup",
                    "clear_temp_files",
                    "remove_shortcut_text",
                    "disable_enhance_pointer_precision",
                    "adjust_mouse_trails",
                    "optimize_mouse_double_click",
                    "optimize_key_repeat_delay",
                    "disable_recent_files",
                    "disable_widgets",
                    "disable_animations",
                    "disable_aero_peak",
                    "disable_balloon_tips",
                    "improve_menu_speed",
                    "disable_game_dvr",
                ]
            ),
        ),
        PresetDefinition(
            id="debloat_lite",
            title="Debloat Lite",
            description="Safe cleanup preset that leans into startup trimming, background quieting, shell cleanup, and obvious extra removal without touching risky switches.",
            accent="#c16cff",
            action_targets=safe_bundle(
                [
                    "disable_startup_delay",
                    "disable_browser_background_mode",
                    "disable_edge_startup_boost",
                    "disable_telemetry_tasks",
                    "disable_ceip_tasks",
                    "disable_onedrive_startup",
                    "adjust_visual_effects",
                    "disable_llmnr",
                    "disable_telemetry",
                    "disable_background_apps",
                    "disable_cortana",
                    "disable_notifications",
                    "disk_cleanup",
                    "clear_temp_files",
                    "optimize_defrag_drives",
                    "check_disk_errors",
                    "remove_shortcut_text",
                    "disable_recent_files",
                    "disable_widgets",
                    "disable_animations",
                    "disable_aero_peak",
                    "disable_balloon_tips",
                    "improve_menu_speed",
                    "disable_game_dvr",
                ]
            ),
        ),
        PresetDefinition(
            id="creator_workstation",
            title="Creator Workstation",
            description="Long-session workstation preset with startup trimming, maintenance, fewer distractions, and performance-safe display and shell changes.",
            accent="#ad72ff",
            action_targets=safe_bundle(
                [
                    "disable_startup_delay",
                    "disable_browser_background_mode",
                    "disable_edge_startup_boost",
                    "disable_telemetry_tasks",
                    "disable_ceip_tasks",
                    "disable_onedrive_startup",
                    "high_performance_power_plan",
                    "adjust_visual_effects",
                    "disable_game_mode",
                    "disable_llmnr",
                    "disable_telemetry",
                    "disable_background_apps",
                    "disable_cortana",
                    "disable_notifications",
                    "disk_cleanup",
                    "clear_temp_files",
                    "optimize_defrag_drives",
                    "check_disk_errors",
                    "remove_shortcut_text",
                    "disable_enhance_pointer_precision",
                    "adjust_mouse_trails",
                    "optimize_mouse_double_click",
                    "optimize_key_repeat_delay",
                    "disable_recent_files",
                    "disable_widgets",
                    "disable_animations",
                    "disable_aero_peak",
                    "disable_balloon_tips",
                    "improve_menu_speed",
                    "disable_game_dvr",
                    "set_highest_refresh_rate",
                ]
            ),
        ),
    ]
    return presets
