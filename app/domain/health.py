"""System health score and recoverable-space targets.

Paid optimizers lead with a single "health" number and a "GB you can recover"
figure. Tweakify computes both from data it already probes, and every finding
points at the concrete actions that address it, so the score is explainable
rather than a marketing gauge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.models import ActionKind


CLEANUP_TARGETS: dict[str, dict[str, Any]] = {
    "temp": {
        "title": "Temporary files",
        "action_id": "clear_temp_files",
        "paths": [r"%TEMP%", r"%SystemRoot%\Temp"],
    },
    "windows_update": {
        "title": "Windows Update download cache",
        "action_id": "clear_windows_update_cache",
        "paths": [r"%SystemRoot%\SoftwareDistribution\Download"],
    },
    "delivery_optimization": {
        "title": "Delivery Optimization cache",
        "action_id": "clear_delivery_optimization_cache",
        "paths": [
            r"%SystemRoot%\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\Cache"
        ],
    },
    "error_reports": {
        "title": "Crash dumps and error reports",
        "action_id": "clear_error_reports",
        "paths": [
            r"%LOCALAPPDATA%\CrashDumps",
            r"%ProgramData%\Microsoft\Windows\WER\ReportArchive",
            r"%ProgramData%\Microsoft\Windows\WER\ReportQueue",
            r"%SystemRoot%\Minidump",
        ],
    },
    "thumbnails": {
        "title": "Thumbnail cache",
        "action_id": "clear_thumbnail_cache",
        "paths": [r"%LOCALAPPDATA%\Microsoft\Windows\Explorer"],
    },
    "browser_cache": {
        "title": "Browser caches",
        "action_id": "clear_browser_cache",
        "paths": [
            r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Cache",
            r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Cache",
            r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data\Default\Cache",
        ],
    },
}

MIN_CLEANUP_BYTES = 50 * 1024**2

# Safe, broadly-agreed tweaks the score nudges toward. Each missing one costs a point.
RECOMMENDED_SAFE_ACTIONS = (
    "disable_startup_delay",
    "disable_telemetry_tasks",
    "disable_advertising_id",
    "disable_start_menu_suggestions",
    "disable_game_dvr",
    "disable_enhance_pointer_precision",
    "set_highest_refresh_rate",
    "disable_browser_background_mode",
    "disable_edge_startup_boost",
    "disable_tailored_experiences",
)


@dataclass(slots=True)
class HealthFinding:
    title: str
    detail: str
    severity: str  # "ok" | "info" | "warning" | "critical"
    penalty: int = 0
    action_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class HealthReport:
    score: int
    grade: str
    findings: list[HealthFinding]
    recoverable_bytes: int

    @property
    def summary(self) -> str:
        issues = [finding for finding in self.findings if finding.penalty]
        recover = format_bytes(self.recoverable_bytes)
        if not issues:
            return f"Health {self.score}/100 ({self.grade}). No issues found. {recover} can be cleaned."
        return f"Health {self.score}/100 ({self.grade}). {len(issues)} item(s) to look at, {recover} can be cleaned."


def format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit in {"B", "KB"} else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"  # pragma: no cover - loop always returns


def _percent(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip().rstrip("%"))
    except ValueError:
        return None


def _grade(score: int) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 55:
        return "Fair"
    return "Needs attention"


def build_health_report(controller) -> HealthReport:
    findings: list[HealthFinding] = []
    diagnostics = {item.id: item.value for item in controller.diagnostics.items}

    ram = _percent(diagnostics.get("ram_pressure"))
    if ram is not None:
        if ram >= 85:
            findings.append(HealthFinding("Memory is nearly full", f"{ram:.0f}% of RAM is in use.", "critical", 15, ["disable_sysmain"]))
        elif ram >= 70:
            findings.append(HealthFinding("Memory pressure is high", f"{ram:.0f}% of RAM is in use.", "warning", 7))
        else:
            findings.append(HealthFinding("Memory pressure is fine", f"{ram:.0f}% of RAM is in use.", "ok"))

    disk = _percent(diagnostics.get("disk_free"))
    if disk is not None:
        cleanup_ids = [target["action_id"] for target in CLEANUP_TARGETS.values()] + ["disk_cleanup"]
        if disk < 10:
            findings.append(HealthFinding("System drive is almost full", f"Only {disk:.0f}% free.", "critical", 20, cleanup_ids))
        elif disk < 20:
            findings.append(HealthFinding("System drive is getting full", f"{disk:.0f}% free.", "warning", 10, cleanup_ids))
        else:
            findings.append(HealthFinding("System drive has room", f"{disk:.0f}% free.", "ok"))

    startup_items = controller.startup_inventory.get("items", []) if controller.startup_inventory else []
    enabled_startup = sum(1 for item in startup_items if getattr(item, "enabled", False))
    if enabled_startup > 15:
        findings.append(HealthFinding("Many apps start with Windows", f"{enabled_startup} startup entries are enabled.", "warning", 10))
    elif enabled_startup > 8:
        findings.append(HealthFinding("Several apps start with Windows", f"{enabled_startup} startup entries are enabled.", "info", 5))

    if str(diagnostics.get("pending_updates", "None")) != "None":
        findings.append(HealthFinding("A restart is pending", "Windows Update is waiting for a reboot.", "warning", 5))

    try:
        uptime = float(diagnostics.get("uptime", "0").split()[0])
    except (ValueError, IndexError, AttributeError):
        uptime = 0.0
    if uptime >= 7 * 24:
        findings.append(HealthFinding("Long uptime", f"Up {uptime / 24:.0f} days. A restart clears leaks and applies updates.", "info", 3))

    sizes = {key: int(value) for key, value in getattr(controller, "cleanup_sizes", {}).items()}
    recoverable = sum(sizes.values())
    gib = 1024**3
    # Only point at cleanups that would free a meaningful amount.
    worth_cleaning = [
        CLEANUP_TARGETS[key]["action_id"]
        for key, size in sorted(sizes.items(), key=lambda item: -item[1])
        if key in CLEANUP_TARGETS and size >= MIN_CLEANUP_BYTES
    ]
    if recoverable >= 5 * gib:
        detail = f"{format_bytes(recoverable)} can be cleaned."
        findings.append(HealthFinding("Lots of junk files", detail, "warning", 10, worth_cleaning))
    elif recoverable >= gib:
        detail = f"{format_bytes(recoverable)} can be cleaned."
        findings.append(HealthFinding("Some junk files", detail, "info", 5, worth_cleaning))

    missing = [
        action_id
        for action_id in RECOMMENDED_SAFE_ACTIONS
        if action_id in controller.actions_by_id
        and controller.actions_by_id[action_id].definition.kind == ActionKind.SETTING
        and controller.compatibility_by_action.get(action_id) is not None
        and controller.compatibility_by_action[action_id].allowed
        and controller.action_states.get(action_id) is not None
        and controller.action_states[action_id].current_state is False
    ]
    if missing:
        findings.append(
            HealthFinding(
                "Recommended tweaks not applied",
                f"{len(missing)} safe tweak(s) are still off.",
                "info",
                min(len(missing), 10),
                missing,
            )
        )

    penalty = sum(finding.penalty for finding in findings)
    score = max(0, min(100, 100 - penalty))
    findings.sort(key=lambda finding: (-finding.penalty, finding.title))
    return HealthReport(score=score, grade=_grade(score), findings=findings, recoverable_bytes=recoverable)
