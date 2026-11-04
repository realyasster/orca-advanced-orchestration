"""Uninstall by restoring the first backup and archiving later edits."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .archive import ArchiveEntry, write_recovery_archive
from .backup import LoadedBackup, load_backup
from .errors import (
    InstallationError,
    InterruptedOperationError,
    PathSafetyError,
    RecoveryRequiredError,
    StateError,
)
from .gitutil import Checkout, resolve_checkout
from .lock import InstallationLock
from .paths import (
    assert_safe_destination,
    atomic_write_bytes,
    ensure_parent_directories,
    inspect_destination,
    mode_matches,
    rel_to_os,
    remove_empty_directories,
    remove_regular_file,
    same_path,
)
from .store import Installation, Store, StoreState, utc_now


@dataclass
class UninstallAction:
    path: str
    kind: str  # "restore" or "remove"
    archive_reason: Optional[str] = None
    missing_before: bool = False
    current_sha256: Optional[str] = None
    current_size: Optional[int] = None
    current_mode: Optional[int] = None


@dataclass
class UninstallPlan:
    actions: List[UninstallAction]
    backup: LoadedBackup

    @property
    def restore_count(self) -> int:
        return sum(1 for item in self.actions if item.kind == "restore")

    @property
    def remove_count(self) -> int:
        return sum(1 for item in self.actions if item.kind == "remove")

    @property
    def archive_entries(self) -> List[UninstallAction]:
        return [item for item in self.actions if item.archive_reason]


@dataclass
class UninstallResult:
    outcome: str
    installation_id: Optional[str] = None
    backup_path: Optional[str] = None
    recovery_archive: Optional[str] = None
    restored: int = 0
    removed: int = 0
    archived: int = 0
    retained_directories: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def _check_identity(record: Installation, checkout: Checkout) -> None:
    if not same_path(record.target_root, checkout.root) or not same_path(
        record.target_git_dir, checkout.git_dir
    ):
        raise StateError(
            "The installation record belongs to a different checkout "
            f"({record.target_root}). Refusing to restore files here."
        )


def _scan(record: Installation, checkout: Checkout) -> Dict[str, dict]:
    """Inspect managed targets without modifying anything."""

    result: Dict[str, dict] = {}
    unexpected: List[str] = []
    root = checkout.root
    for item in record.files:
        try:
            assert_safe_destination(root, item.path)
            state = inspect_destination(rel_to_os(root, item.path), with_hash=True)
        except Exception as exc:
            unexpected.append(f"{item.path} ({exc})")
            continue
        if state.exists and not state.is_file:
            unexpected.append(f"{item.path} (expected a regular file)")
            continue
        result[item.path] = {
            "exists": state.exists,
            "sha256": state.sha256,
            "size": state.size,
            "mode": state.mode,
        }
    if unexpected:
        raise InstallationError(
            "Unexpected targets were found; no target file was changed. "
            "Move them away and retry: " + "; ".join(unexpected[:5])
        )
    return result


def _plan(record: Installation, checkout: Checkout, backup: LoadedBackup) -> UninstallPlan:
    current = _scan(record, checkout)
    actions: List[UninstallAction] = []
    for item in record.files:
        state = current[item.path]
        exists = state["exists"]
        sha = state["sha256"]
        if item.original_existed:
            reason = None
            missing = not exists
            if exists and sha != item.installed_sha256:
                if sha != item.original_sha256:
                    reason = "modified-after-install"
            if missing:
                reason = "missing-before-uninstall"
            actions.append(
                UninstallAction(
                    path=item.path,
                    kind="restore",
                    archive_reason=reason,
                    missing_before=missing,
                    current_sha256=sha,
                    current_size=state["size"],
                    current_mode=state["mode"],
                )
            )
        else:
            if not exists:
                continue
            reason = None
            if sha != item.installed_sha256:
                reason = "modified-after-install"
            actions.append(
                UninstallAction(
                    path=item.path,
                    kind="remove",
                    archive_reason=reason,
                    current_sha256=sha,
                    current_size=state["size"],
                    current_mode=state["mode"],
                )
            )
    return UninstallPlan(actions=actions, backup=backup)


def _archive_entries(plan: UninstallPlan) -> List[ArchiveEntry]:
    return [
        ArchiveEntry(
            path=action.path,
            reason=action.archive_reason or "modified-after-install",
            missing=action.missing_before,
            sha256=action.current_sha256,
            size=action.current_size,
            mode=action.current_mode,
        )
        for action in plan.archive_entries
    ]


def _save(store: Store, record: Installation) -> None:
    state = store.load()
    history = list(state.history) if state else []
    store.save(StoreState(installation=record, history=history))


def _apply_actions(
    store: Store,
    record: Installation,
    checkout: Checkout,
    plan: UninstallPlan,
) -> None:
    root = checkout.root
    for action in plan.actions:
        if action.kind == "restore":
            data, mode = plan.backup.read(action.path)
            ensure_parent_directories(root, action.path)
            atomic_write_bytes(rel_to_os(root, action.path), data, mode)
        else:
            remove_regular_file(rel_to_os(root, action.path))
        record.progress.restored_paths.append(action.path)
        record.updated_at = utc_now()
        _save(store, record)


def _verify_restored(record: Installation, checkout: Checkout) -> List[str]:
    problems: List[str] = []
    root = checkout.root
    for item in record.files:
        try:
            assert_safe_destination(root, item.path)
            state = inspect_destination(rel_to_os(root, item.path), with_hash=True)
        except Exception as exc:
            problems.append(f"{item.path}: {exc}")
            continue
        if item.original_existed:
            if not state.exists or not state.is_file:
                problems.append(f"{item.path}: original file is missing")
            elif state.sha256 != item.original_sha256 or state.size != item.original_size:
                problems.append(f"{item.path}: original content mismatch")
            elif not mode_matches(rel_to_os(root, item.path), int(item.original_mode or 0)):
                problems.append(f"{item.path}: original permission mismatch")
        elif state.exists:
            problems.append(f"{item.path}: installed file still exists")
    return problems


def _uninstall_record(
    store: Store,
    checkout: Checkout,
    record: Installation,
    resuming: bool,
) -> UninstallResult:
    _check_identity(record, checkout)
    backup = load_backup(store, record)
    plan = _plan(record, checkout, backup)
    archive_dir = write_recovery_archive(
        store, record.installation_id, checkout.root, _archive_entries(plan)
    )

    record.status = "uninstalling"
    record.progress.phase = "uninstalling"
    record.progress.last_error = None
    record.updated_at = utc_now()
    if archive_dir is not None and str(archive_dir) not in record.recovery_archives:
        record.recovery_archives.append(str(archive_dir))
    _save(store, record)

    try:
        _apply_actions(store, record, checkout, plan)
    except (PathSafetyError, StateError, InstallationError):
        record.status = "recovery_required"
        record.progress.phase = "recovery_required"
        record.progress.last_error = "uninstall stopped at an unsafe or unexpected target"
        record.updated_at = utc_now()
        try:
            _save(store, record)
        except Exception:
            pass
        raise
    except OSError as exc:
        record.progress.last_error = str(exc)
        record.updated_at = utc_now()
        try:
            _save(store, record)
        except Exception:
            pass
        raise InstallationError(
            f"Uninstall was interrupted: {exc}. The record is kept as 'uninstalling'; "
            "re-run uninstall to resume from the existing backup and archives."
        ) from exc

    retained = remove_empty_directories(checkout.root, record.created_directories)
    problems = _verify_restored(record, checkout)
    if problems:
        record.status = "recovery_required"
        record.progress.phase = "recovery_required"
        record.progress.last_error = "verification after restore failed: " + "; ".join(problems[:5])
        record.completed_at = utc_now()
        record.updated_at = utc_now()
        try:
            _save(store, record)
        except Exception:
            pass
        raise RecoveryRequiredError(
            "Uninstall finished writing files but verification failed. "
            f"Pending: {'; '.join(problems[:5])}. Backup: {record.backup_path}."
        )

    record.status = "uninstalled"
    record.progress.phase = "complete"
    record.progress.last_error = None
    record.completed_at = utc_now()
    record.updated_at = utc_now()
    _save(store, record)
    notes = []
    if resuming:
        notes.append("Resumed an interrupted uninstall.")
    if retained:
        notes.append(
            "Kept non-empty directories: " + ", ".join(retained)
        )
    return UninstallResult(
        outcome="uninstalled",
        installation_id=record.installation_id,
        backup_path=record.backup_path,
        recovery_archive=str(archive_dir) if archive_dir else None,
        restored=plan.restore_count,
        removed=plan.remove_count,
        archived=len(plan.archive_entries),
        retained_directories=retained,
        notes=notes,
    )


def resume_interrupted_uninstall(
    store: Store, checkout: Checkout, record: Installation
) -> UninstallResult:
    return _uninstall_record(store, checkout, record, resuming=True)


def uninstall(source: Path | str, dry_run: bool = False) -> UninstallResult:
    checkout = resolve_checkout(source)
    store = Store(checkout)
    state = store.load()
    record = state.installation if state else None

    if record is None or record.status == "uninstalled":
        return UninstallResult(
            outcome="not-installed",
            installation_id=record.installation_id if record else None,
            backup_path=record.backup_path if record else None,
            notes=["No active installation was found; nothing to do."],
        )
    if record.status == "recovery_required":
        raise RecoveryRequiredError(
            f"The installation is in recovery_required state. Inspect {store.base_dir} "
            "before changing anything."
        )
    if record.status in ("installing", "uninstalling", "updating"):
        if dry_run:
            return UninstallResult(
                outcome="dry-run",
                installation_id=record.installation_id,
                backup_path=record.backup_path,
                notes=[
                    "An interrupted operation is recorded. A real uninstall would "
                    "reconcile it first.",
                    "No files would be changed by this dry run.",
                ],
            )
        with InstallationLock(store, "uninstall"):
            state = store.load()
            record = state.installation if state else None
            if record is None or record.status == "uninstalled":
                return UninstallResult(outcome="not-installed")
            if record.status == "recovery_required":
                raise RecoveryRequiredError(
                    f"The installation is in recovery_required state. Inspect {store.base_dir}."
                )
            if record.status == "installing":
                from .recovery import reconcile_locked

                reconcile_locked(store, checkout, "uninstall")
                return UninstallResult(
                    outcome="recovered-install",
                    installation_id=record.installation_id,
                    backup_path=record.backup_path,
                    notes=[
                        "Recovered an interrupted install and restored original files. "
                        "There is no active installation to remove."
                    ],
                )
            if record.status == "updating":
                from .recovery import reconcile_locked

                reconcile_locked(store, checkout, "uninstall")
                raise InterruptedOperationError(
                    "Recovered an interrupted update and restored the previously "
                    "installed version. Re-run uninstall to remove it."
                )
            return _uninstall_record(store, checkout, record, resuming=True)

    if dry_run:
        _check_identity(record, checkout)
        backup = load_backup(store, record)
        plan = _plan(record, checkout, backup)
        return UninstallResult(
            outcome="dry-run",
            installation_id=record.installation_id,
            backup_path=record.backup_path,
            restored=plan.restore_count,
            removed=plan.remove_count,
            archived=len(plan.archive_entries),
            notes=[
                "Dry run: no files, backups, recovery archives, state, or locks were changed.",
                f"Would restore {plan.restore_count} files, remove {plan.remove_count} files, "
                f"and archive {len(plan.archive_entries)} changed/missing entries.",
            ],
        )

    with InstallationLock(store, "uninstall"):
        state = store.load()
        record = state.installation if state else None
        if record is None or record.status == "uninstalled":
            return UninstallResult(outcome="not-installed")
        if record.status == "recovery_required":
            raise RecoveryRequiredError(
                f"The installation is in recovery_required state. Inspect {store.base_dir}."
            )
        if record.status in ("installing", "uninstalling", "updating"):
            if record.status == "installing":
                from .recovery import reconcile_locked

                reconcile_locked(store, checkout, "uninstall")
                return UninstallResult(
                    outcome="recovered-install",
                    installation_id=record.installation_id,
                    backup_path=record.backup_path,
                    notes=[
                        "Recovered an interrupted install and restored original files. "
                        "There is no active installation to remove."
                    ],
                )
            if record.status == "updating":
                from .recovery import reconcile_locked

                reconcile_locked(store, checkout, "uninstall")
                raise InterruptedOperationError(
                    "Recovered an interrupted update and restored the previously "
                    "installed version. Re-run uninstall to remove it."
                )
            return _uninstall_record(store, checkout, record, resuming=True)
        return _uninstall_record(store, checkout, record, resuming=False)
