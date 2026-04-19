from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import DiagnosticItem, DiagnosticsSnapshot


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
                detail="Current process sample.",
            ),
            DiagnosticItem(
                id="ram_pressure",
                title="RAM Pressure",
                value=data["ram_pressure"],
                status="ok",
                detail="Estimated memory pressure snapshot.",
            ),
            DiagnosticItem(
                id="disk_free",
                title="Disk Free",
                value=data["disk_free_percent"],
                status="ok",
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
                detail="Virtualization-based security state.",
            ),
            DiagnosticItem(
                id="memory_integrity",
                title="Memory Integrity",
                value=data["memory_integrity"],
                status="info",
                detail="Kernel memory integrity state.",
            ),
            DiagnosticItem(
                id="indexing",
                title="Indexing",
                value=data["indexing_state"],
                status="info",
                detail="Windows Search service state.",
            ),
            DiagnosticItem(
                id="delivery_optimization",
                title="Delivery Optimization",
                value=data["delivery_optimization"],
                status="info",
                detail="Delivery Optimization service state.",
            ),
        ]
        return DiagnosticsSnapshot(
            captured_at=datetime.now(UTC).isoformat(),
            items=items,
        )
