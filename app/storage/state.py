from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app.domain.models import AppSettings, ApplyTransaction, DiagnosticsSnapshot, SnapshotManifest


def _atomic_write_json(path: Path, payload: Any) -> Path:
    """Write JSON so a crash or power loss never leaves a half-written file behind.

    Snapshots are the only record of what Tweakify changed. A truncated snapshot
    means a change that can no longer be rolled back.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return path


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class TweakifyStateStore:
    MAX_TRANSACTIONS = 200

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
        return _atomic_write_json(self.snapshots_dir / f"{snapshot.snapshot_id}.json", snapshot.to_dict())

    def load_snapshot(self, snapshot_id: str) -> SnapshotManifest | None:
        if Path(snapshot_id).name != snapshot_id:
            return None
        payload = _read_json(self.snapshots_dir / f"{snapshot_id}.json")
        if not isinstance(payload, dict):
            return None
        try:
            return SnapshotManifest.from_dict(payload)
        except (KeyError, TypeError, ValueError):
            return None

    def list_snapshots(self) -> list[SnapshotManifest]:
        snapshots: list[SnapshotManifest] = []
        for path in self.snapshots_dir.glob("*.json"):
            payload = _read_json(path)
            if not isinstance(payload, dict):
                continue
            try:
                snapshots.append(SnapshotManifest.from_dict(payload))
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(snapshots, key=lambda item: item.created_at, reverse=True)

    def latest_baseline(self) -> SnapshotManifest | None:
        for snapshot in self.list_snapshots():
            if snapshot.is_baseline:
                return snapshot
        return None

    def save_transaction(self, transaction: ApplyTransaction) -> Path:
        path = _atomic_write_json(self.logs_dir / f"{transaction.transaction_id}.json", transaction.to_dict())
        self._prune_transactions()
        return path

    def list_transactions(self) -> list[ApplyTransaction]:
        transactions: list[ApplyTransaction] = []
        for path in self.logs_dir.glob("*.json"):
            payload = _read_json(path)
            if not isinstance(payload, dict):
                continue
            try:
                transactions.append(ApplyTransaction.from_dict(payload))
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(transactions, key=lambda item: item.created_at, reverse=True)

    def _prune_transactions(self) -> None:
        logs = sorted(self.logs_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        for stale in logs[self.MAX_TRANSACTIONS :]:
            stale.unlink(missing_ok=True)

    def save_diagnostics(self, diagnostics: DiagnosticsSnapshot) -> Path:
        return _atomic_write_json(self.cache_dir / "diagnostics.json", diagnostics.to_dict())

    def load_diagnostics(self) -> DiagnosticsSnapshot | None:
        payload = _read_json(self.cache_dir / "diagnostics.json")
        if not isinstance(payload, dict):
            return None
        try:
            return DiagnosticsSnapshot.from_dict(payload)
        except (KeyError, TypeError, ValueError):
            return None

    def save_settings(self, settings: AppSettings) -> Path:
        return _atomic_write_json(self.settings_path, settings.to_dict())

    def load_settings(self) -> AppSettings:
        if not self.settings_path.exists():
            settings = AppSettings()
            self.save_settings(settings)
            return settings
        payload = _read_json(self.settings_path)
        if not isinstance(payload, dict):
            # Keep the unreadable file for inspection instead of silently overwriting it.
            self.settings_path.replace(self.settings_path.with_suffix(".corrupt.json"))
            settings = AppSettings()
            self.save_settings(settings)
            return settings
        return AppSettings.from_dict(payload)
