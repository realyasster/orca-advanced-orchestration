"""Read-only installation status reporting."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .gitutil import resolve_checkout
from .installer import FileComparison, compare_installed, verify_installed
from .lock import inspect_lock
from .backup import load_backup
from .store import Installation, Store


@dataclass
class StatusReport:
    outcome: str
    target: str
    data_dir: str
    record: Optional[Installation] = None
    comparison: Optional[FileComparison] = None
    lock: Optional[str] = None

    def render(self, limit: int = 10) -> str:
        lines: List[str] = []
        lines.append(f"Installation: {self.outcome}")
        lines.append(f"Target: {self.target}")
        if self.record is None:
            lines.append(f"Record directory: {self.data_dir} (no installation record)")
            if self.lock:
                lines.append(f"Active operation: {self.lock}")
            return "\n".join(lines)

        record = self.record
        lines.append(f"Installation ID: {record.installation_id}")
        lines.append(f"Created: {record.created_at}")
        lines.append(f"Updated: {record.updated_at}")
        if record.completed_at:
            lines.append(f"Completed: {record.completed_at}")
        lines.append(
            f"Package: {record.package_version or 'unknown'} (base {record.package_base_commit}, "
            f"implementation {record.package_implementation_commit or 'unknown'})"
        )
        lines.append(f"Package fingerprint: {record.package_fingerprint}")
        lines.append(f"Backup: {record.backup_path}")
        if record.recovery_archives:
            lines.append("Recovery archives:")
            for archive in record.recovery_archives:
                lines.append(f"  {archive}")
        else:
            lines.append("Recovery archives: none")
        lines.append(f"Progress: {record.progress.phase}")
        if record.progress.last_error:
            lines.append(f"Last error: {record.progress.last_error}")

        if self.comparison is not None:
            comparison = self.comparison
            total = len(record.files)
            changed = (
                len(comparison.modified)
                + len(comparison.missing)
                + len(comparison.unexpected)
                + len(comparison.mode_changed)
            )
            lines.append(
                f"Managed files: {total} total, {total - changed} match the installed record, "
                f"{len(comparison.modified)} modified, {len(comparison.missing)} missing, "
                f"{len(comparison.unexpected)} unexpected, "
                f"{len(comparison.mode_changed)} permission changes"
            )
            _append_list(lines, "Modified since install", comparison.modified, limit)
            _append_list(lines, "Missing since install", comparison.missing, limit)
            _append_list(lines, "Unexpected paths", comparison.unexpected, limit)
            _append_list(lines, "Permission changes", comparison.mode_changed, limit)
        if self.lock:
            lines.append(f"Active operation: {self.lock}")
        return "\n".join(lines)


def _append_list(lines: List[str], label: str, items: List[str], limit: int) -> None:
    if not items:
        return
    lines.append(f"{label}:")
    for item in items[:limit]:
        lines.append(f"  {item}")
    if len(items) > limit:
        lines.append(f"  ... and {len(items) - limit} more")


def collect_status(source: Path | str) -> StatusReport:
    checkout = resolve_checkout(source)
    store = Store(checkout)
    state = store.load()
    record = state.installation if state else None
    lock = inspect_lock(store)
    if record is None:
        return StatusReport(
            outcome="not installed",
            target=str(checkout.root),
            data_dir=str(store.base_dir),
            lock=lock,
        )
    comparison = None
    if record.status == "installed":
        comparison = compare_installed(record, checkout.root)
        outcome = "installed"
    elif record.status == "uninstalled":
        outcome = "uninstalled"
    elif record.status == "recovery_required":
        outcome = "recovery required"
    elif record.status in ("installing", "uninstalling", "updating"):
        outcome = f"interrupted ({record.status})"
        comparison = compare_installed(record, checkout.root)
    else:
        outcome = record.status
    return StatusReport(
        outcome=outcome,
        target=str(checkout.root),
        data_dir=str(store.base_dir),
        record=record,
        comparison=comparison,
        lock=lock,
    )


@dataclass
class VerificationReport:
    target: str
    outcome: str
    problems: List[str]
    record: Optional[Installation] = None

    def render(self) -> str:
        lines = [f"Installation: {self.outcome}", f"Target: {self.target}"]
        if self.record is not None:
            lines.append(f"Package: {self.record.package_version or 'unknown'}")
            lines.append(f"Backup: {self.record.backup_path}")
        if self.problems:
            lines.append(f"Problems: {len(self.problems)}")
            for problem in self.problems:
                lines.append(f"  {problem}")
        else:
            lines.append("Problems: none")
        return "\n".join(lines)


def verify_installation(source: Path | str) -> VerificationReport:
    checkout = resolve_checkout(source)
    store = Store(checkout)
    state = store.load()
    record = state.installation if state else None
    if record is None:
        return VerificationReport(
            target=str(checkout.root),
            outcome="not installed",
            problems=[],
        )
    if record.status == "uninstalled":
        return VerificationReport(
            target=str(checkout.root),
            outcome="uninstalled",
            problems=[],
            record=record,
        )
    if record.status == "recovery_required":
        return VerificationReport(
            target=str(checkout.root),
            outcome="recovery required",
            problems=["the installation record requires manual recovery"],
            record=record,
        )
    problems: List[str] = []
    if record.status == "installed":
        problems.extend(verify_installed(record, checkout.root))
    elif record.status in ("installing", "updating", "uninstalling"):
        problems.append(
            f"interrupted operation recorded: {record.status}; run the matching "
            "install/update/uninstall command to reconcile it"
        )
    elif record.status not in ("uninstalled", "recovery_required"):
        problems.append(f"unexpected installation state: {record.status}")
    try:
        load_backup(store, record)
    except Exception as exc:
        problems.append(f"backup: {exc}")
    return VerificationReport(
        target=str(checkout.root),
        outcome=record.status,
        problems=problems,
        record=record,
    )
