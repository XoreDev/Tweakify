from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import DiagnosticItem, DiagnosticsSnapshot


def _percent(value: object) -> float | None:
    try:
        return float(str(value).strip().rstrip("%"))
    except ValueError:
        return None


def _threshold_status(value: float | None, warning: float, critical: float, higher_is_worse: bool = True) -> str:
    if value is None:
        return "info"
    if higher_is_worse:
        if value >= critical:
            return "critical"
        if value >= warning:
            return "warning"
        return "ok"
    if value <= critical:
        return "critical"
    if value <= warning:
        return "warning"
    return "ok"


class DiagnosticsCollector:
    def __init__(self, platform) -> None:
        self.platform = platform

    def collect(self, startup_inventory: dict[str, object] | None = None) -> DiagnosticsSnapshot:
        startup_inventory = startup_inventory or self.platform.startup_inventory()
        data = self.platform.diagnostic_probe(startup_count=int(startup_inventory["count"]))
        items = [
            DiagnosticItem(
                id="startup_count",
                title="Startup Entries",
                value=str(data["startup_count"]),
                status="info",
                detail="Run keys and Startup folders detected.",
            ),
            DiagnosticItem(
                id="startup_duplicates",
                title="Startup Duplicates",
                value=str(len(startup_inventory["duplicates"])),
                status="warning" if startup_inventory["duplicates"] else "ok",
                detail="Duplicate names seen across startup locations.",
            ),
            DiagnosticItem(
                id="top_idle_cpu",
                title="Top CPU Users",
                value=", ".join(data["top_idle_cpu_users"]),
                status="info",
                detail="Processes with the most CPU time since they started.",
            ),
            DiagnosticItem(
                id="ram_pressure",
                title="RAM Pressure",
                value=data["ram_pressure"],
                status=_threshold_status(_percent(data["ram_pressure"]), warning=70, critical=85),
                detail="Share of physical memory in use right now.",
            ),
            DiagnosticItem(
                id="disk_free",
                title="Disk Free",
                value=data["disk_free_percent"],
                status=_threshold_status(_percent(data["disk_free_percent"]), warning=20, critical=10, higher_is_worse=False),
                detail=f"{data['drive_type']} system drive free space.",
            ),
            DiagnosticItem(
                id="pending_updates",
                title="Pending Updates",
                value=data["pending_updates"],
                status="warning" if data["pending_updates"] != "None" else "ok",
                detail="Reboot-required or update queue indicators.",
            ),
            DiagnosticItem(
                id="vbs_status",
                title="VBS",
                value=data["vbs_status"],
                status="info",
                detail="Virtualization-based security policy. It protects the kernel but can cost some gaming FPS.",
            ),
            DiagnosticItem(
                id="memory_integrity",
                title="Memory Integrity",
                value=data["memory_integrity"],
                status="info",
                detail="Kernel memory integrity (HVCI) policy.",
            ),
            DiagnosticItem(
                id="indexing",
                title="Indexing",
                value=data["indexing_state"],
                status="info",
                detail="Windows Search service start mode.",
            ),
            DiagnosticItem(
                id="delivery_optimization",
                title="Delivery Optimization",
                value=data["delivery_optimization"],
                status="info",
                detail="Delivery Optimization service start mode.",
            ),
        ]
        if data.get("uptime_hours") is not None:
            hours = float(data["uptime_hours"])
            items.append(
                DiagnosticItem(
                    id="uptime",
                    title="Uptime",
                    value=f"{hours:.0f} h",
                    status="warning" if hours >= 7 * 24 else "ok",
                    detail="Time since the last full restart. Fast Startup shutdowns do not reset it.",
                )
            )
        if data.get("power_plan"):
            items.append(
                DiagnosticItem(
                    id="power_plan",
                    title="Power Plan",
                    value=str(data["power_plan"]),
                    status="info",
                    detail="Active Windows power scheme.",
                )
            )
        return DiagnosticsSnapshot(
            captured_at=datetime.now(UTC).isoformat(),
            items=items,
        )
