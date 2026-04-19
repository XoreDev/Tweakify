from __future__ import annotations

import json
import os
from pathlib import Path

from app.domain.models import AppSettings, ApplyTransaction, DiagnosticsSnapshot, SnapshotManifest


class TweakifyStateStore:
    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            root = local_app_data / "Tweakify"
        self.root = Path(root)
        self.snapshots_dir = self.root / "snapshots"
        self.logs_dir = self.root / "apply-logs"
        self.cache_dir = self.root / "cache"
        self.plans_dir = self.root / "plans"
        self.settings_path = self.root / "settings.json"
        for path in (self.root, self.snapshots_dir, self.logs_dir, self.cache_dir, self.plans_dir):
            path.mkdir(parents=True, exist_ok=True)

    def save_snapshot(self, snapshot: SnapshotManifest) -> Path:
        path = self.snapshots_dir / f"{snapshot.snapshot_id}.json"
        path.write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
        return path

    def load_snapshot(self, snapshot_id: str) -> SnapshotManifest | None:
        path = self.snapshots_dir / f"{snapshot_id}.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return SnapshotManifest.from_dict(payload)

    def list_snapshots(self) -> list[SnapshotManifest]:
        snapshots = [
            SnapshotManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
            for path in self.snapshots_dir.glob("*.json")
        ]
        return sorted(snapshots, key=lambda item: item.created_at, reverse=True)

    def latest_baseline(self) -> SnapshotManifest | None:
        for snapshot in self.list_snapshots():
            if snapshot.is_baseline:
                return snapshot
        return None

    def save_transaction(self, transaction: ApplyTransaction) -> Path:
        path = self.logs_dir / f"{transaction.transaction_id}.json"
        path.write_text(json.dumps(transaction.to_dict(), indent=2), encoding="utf-8")
        return path

    def list_transactions(self) -> list[ApplyTransaction]:
        transactions = [
            ApplyTransaction.from_dict(json.loads(path.read_text(encoding="utf-8")))
            for path in self.logs_dir.glob("*.json")
        ]
        return sorted(transactions, key=lambda item: item.created_at, reverse=True)

    def save_diagnostics(self, diagnostics: DiagnosticsSnapshot) -> Path:
        path = self.cache_dir / "diagnostics.json"
        path.write_text(json.dumps(diagnostics.to_dict(), indent=2), encoding="utf-8")
        return path

    def load_diagnostics(self) -> DiagnosticsSnapshot | None:
        path = self.cache_dir / "diagnostics.json"
        if not path.exists():
            return None
        return DiagnosticsSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save_settings(self, settings: AppSettings) -> Path:
        self.settings_path.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
        return self.settings_path

    def load_settings(self) -> AppSettings:
        if not self.settings_path.exists():
            settings = AppSettings()
            self.save_settings(settings)
            return settings
        return AppSettings.from_dict(json.loads(self.settings_path.read_text(encoding="utf-8")))
