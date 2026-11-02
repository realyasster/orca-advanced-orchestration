"""Install the bundle with a verified backup, durable journal, and rollback."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import shutil

from .archive import ArchiveEntry, write_recovery_archive
from .backup import LoadedBackup, create_backup, load_backup
from .bundle import Bundle, load_bundle
from .errors import (
    InstallationError,
    InterruptedOperationError,
    RecoveryRequiredError,
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
from .planner import InstallPlan, PreparedFile, build_install_plan
from .store import (
    FileRecord,
    Installation,
    Progress,
    Store,
    StoreState,
    new_identifier,
    utc_now,
)


@dataclass
class InstallResult:
    outcome: str
    installation_id: Optional[str] = None
    backup_path: Optional[str] = None
    added: int = 0
    updated: int = 0
    preserved_edits: List[str] = field(default_factory=list)
    modified_since_install: List[str] = field(default_factory=list)
    missing_since_install: List[str] = field(default_factory=list)
    unexpected_paths: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class FileComparison:
    modified: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    unexpected: List[str] = field(default_factory=list)
    mode_changed: List[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.modified or self.missing or self.unexpected or self.mode_changed)


def compare_installed(record: Installation, root: Path) -> FileComparison:
    comparison = FileComparison()
    for item in record.files:
        try:
            assert_safe_destination(root, item.path)
            state = inspect_destination(rel_to_os(root, item.path), with_hash=True)
        except Exception:
            comparison.unexpected.append(item.path)
            continue
        if not state.exists:
            comparison.missing.append(item.path)
        elif not state.is_file:
            comparison.unexpected.append(item.path)
        elif state.sha256 != item.installed_sha256 or state.size != item.installed_size:
            comparison.modified.append(item.path)
        elif not mode_matches(rel_to_os(root, item.path), item.installed_mode):
            comparison.mode_changed.append(item.path)
    return comparison


def _record_from_plan(
    checkout: Checkout,
    bundle: Bundle,
    installation_id: str,
    plan: InstallPlan,
    backup_root: Path,
    backup_manifest: Path,
) -> Installation:
    now = utc_now()
    files = [
        FileRecord(
            path=item.path,
            original_existed=item.original_existed,
            original_sha256=item.original_sha256,
            original_size=item.original_size,
            original_mode=item.original_mode,
            installed_sha256=item.sha256,
            installed_size=len(item.data),
            installed_mode=item.mode,
        )
        for item in plan.files
    ]
    return Installation(
        installation_id=installation_id,
        status="installing",
        created_at=now,
        updated_at=now,
        target_root=str(checkout.root),
        target_git_dir=str(checkout.git_dir),
        head_at_install=checkout.head,
        package_base_commit=bundle.base_commit,
        package_implementation_commit=bundle.implementation_commit,
        package_fingerprint=bundle.fingerprint,
        backup_path=str(backup_root),
        backup_manifest_path=str(backup_manifest),
        recovery_archives=[],
        created_directories=list(plan.created_directories),
        files=files,
        progress=Progress(phase="writing"),
    )


def _cleanup_unreferenced_install_dir(store: Store, installation_id: str) -> None:
    path = store.install_dir(installation_id)
    try:
        path.resolve().relative_to(store.base_dir.resolve())
    except ValueError:
        return
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _verify_target_unchanged(item: PreparedFile, root: Path) -> None:
    assert_safe_destination(root, item.path)
    state = inspect_destination(rel_to_os(root, item.path), with_hash=True)
    if item.original_existed:
        if not state.exists or not state.is_file:
            raise InstallationError(
                f"'{item.path}' disappeared while preparing the installation. "
                "No further file was changed; the operation will be rolled back."
            )
        if state.sha256 != item.original_sha256 or state.size != item.original_size:
            raise InstallationError(
                f"'{item.path}' changed while preparing the installation. "
                "The operation will be rolled back from backup."
            )
    elif state.exists:
        raise InstallationError(
            f"'{item.path}' appeared while preparing the installation. "
            "The operation will be rolled back from backup."
        )


def _write_plan(store: Store, checkout: Checkout, state: StoreState, plan: InstallPlan) -> None:
    record = state.installation
    assert record is not None
    root = checkout.root
    for item in plan.files:
        _verify_target_unchanged(item, root)
        ensure_parent_directories(root, item.path, record.created_directories)
        atomic_write_bytes(rel_to_os(root, item.path), item.data, item.mode)
        record.progress.completed_paths.append(item.path)
        record.updated_at = utc_now()
        store.save(state)

    problems = verify_installed(record, root)
    if problems:
        raise InstallationError(
            "Files were written but failed post-install verification: " + "; ".join(problems[:5])
        )


def verify_installed(record: Installation, root: Path) -> List[str]:
    problems: List[str] = []
    for item in record.files:
        try:
            assert_safe_destination(root, item.path)
            state = inspect_destination(rel_to_os(root, item.path), with_hash=True)
        except Exception as exc:
            problems.append(f"{item.path}: {exc}")
            continue
        if not state.exists or not state.is_file:
            problems.append(f"{item.path}: missing")
        elif state.sha256 != item.installed_sha256 or state.size != item.installed_size:
            problems.append(f"{item.path}: content mismatch")
        elif not mode_matches(rel_to_os(root, item.path), item.installed_mode):
            problems.append(f"{item.path}: permission mismatch")
    return problems


def verify_originals(record: Installation, root: Path) -> List[str]:
    problems: List[str] = []
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
            problems.append(f"{item.path}: still exists after rollback")
    return problems


def _rollback(
    store: Store,
    checkout: Checkout,
    record: Installation,
    backup: Optional[LoadedBackup],
) -> List[str]:
    problems: List[str] = []
    root = checkout.root
    for item in record.files:
        try:
            assert_safe_destination(root, item.path)
        except Exception as exc:
            problems.append(f"{item.path}: unsafe path ({exc})")
            continue
        try:
            if item.original_existed:
                if backup is None:
                    problems.append(f"{item.path}: backup is unavailable")
                    continue
                data, mode = backup.read(item.path)
                ensure_parent_directories(root, item.path)
                atomic_write_bytes(rel_to_os(root, item.path), data, mode)
            else:
                state = inspect_destination(rel_to_os(root, item.path))
                if state.exists:
                    if state.is_file:
                        remove_regular_file(rel_to_os(root, item.path))
                    else:
                        problems.append(
                            f"{item.path}: refusing to remove an unexpected non-file"
                        )
        except Exception as exc:
            problems.append(f"{item.path}: {exc}")
    try:
        remove_empty_directories(root, record.created_directories)
    except Exception as exc:
        problems.append(f"directory cleanup: {exc}")
    problems.extend(verify_originals(record, root))
    return problems


def _recovery_entries_for_rollback(
    record: Installation, root: Path
) -> tuple[List[ArchiveEntry], List[str]]:
    """Find content that is neither the original nor the installed version.

    This is usually a post-crash edit. It is archived before an interrupted
    install is rolled back so reconciliation cannot silently discard it.
    """

    entries: List[ArchiveEntry] = []
    problems: List[str] = []
    for item in record.files:
        try:
            assert_safe_destination(root, item.path)
            state = inspect_destination(rel_to_os(root, item.path), with_hash=True)
        except Exception as exc:
            problems.append(f"{item.path}: {exc}")
            continue
        if state.exists and not state.is_file:
            problems.append(f"{item.path}: expected a regular file, found another type")
            continue
        if item.original_existed:
            if not state.exists:
                entries.append(
                    ArchiveEntry(
                        path=item.path,
                        reason="missing-before-recovery",
                        missing=True,
                        sha256=None,
                        size=None,
                        mode=None,
                    )
                )
            elif state.sha256 not in (item.original_sha256, item.installed_sha256):
                entries.append(
                    ArchiveEntry(
                        path=item.path,
                        reason="unexpected-content-during-recovery",
                        missing=False,
                        sha256=state.sha256,
                        size=state.size,
                        mode=state.mode,
                    )
                )
        elif state.exists and state.sha256 != item.installed_sha256:
            entries.append(
                ArchiveEntry(
                    path=item.path,
                    reason="unexpected-content-during-recovery",
                    missing=False,
                    sha256=state.sha256,
                    size=state.size,
                    mode=state.mode,
                )
            )
    return entries, problems


def rollback_interrupted_install(store: Store, checkout: Checkout, record: Installation) -> None:
    """Reconcile a journal left in ``installing`` state."""

    if not (same_path(record.target_root, checkout.root) and same_path(
        record.target_git_dir, checkout.git_dir
    )):
        raise RecoveryRequiredError(
            "The installation record belongs to a different checkout "
            f"({record.target_root}). Refusing to restore files here. "
            f"Inspect {store.base_dir}."
        )
    state = store.load()
    history = list(state.history) if state else []
    try:
        backup = load_backup(store, record)
    except Exception as exc:
        record.status = "recovery_required"
        record.progress.phase = "recovery_required"
        record.progress.last_error = f"backup verification failed during recovery: {exc}"
        record.updated_at = utc_now()
        store.save(StoreState(installation=record, history=history))
        raise RecoveryRequiredError(
            f"An interrupted install was found, but its backup cannot be verified: {exc}. "
            f"Inspect {store.base_dir} before changing anything."
        ) from exc

    entries, problems = _recovery_entries_for_rollback(record, checkout.root)
    if problems:
        record.status = "recovery_required"
        record.progress.phase = "recovery_required"
        record.progress.last_error = "unexpected target content before rollback: " + "; ".join(
            problems[:5]
        )
        record.updated_at = utc_now()
        store.save(StoreState(installation=record, history=history))
        raise RecoveryRequiredError(
            "An interrupted install has unexpected target types; refusing to overwrite them. "
            f"Pending: {'; '.join(problems[:5])}. Inspect {store.base_dir}."
        )
    if entries:
        try:
            archive = write_recovery_archive(
                store, record.installation_id, checkout.root, entries
            )
        except Exception as exc:
            record.status = "recovery_required"
            record.progress.phase = "recovery_required"
            record.progress.last_error = f"recovery archive failed: {exc}"
            record.updated_at = utc_now()
            store.save(StoreState(installation=record, history=history))
            raise RecoveryRequiredError(
                "An interrupted install has content that could not be archived safely; "
                f"refusing to roll it back: {exc}. Inspect {store.base_dir}."
            ) from exc
        if archive is not None:
            record.recovery_archives.append(str(archive))
            record.updated_at = utc_now()
            store.save(StoreState(installation=record, history=history))

    problems = _rollback(store, checkout, record, backup)
    if problems:
        record.status = "recovery_required"
        record.progress.phase = "recovery_required"
        record.progress.last_error = "rollback incomplete: " + "; ".join(problems[:5])
        record.updated_at = utc_now()
        store.save(StoreState(installation=record, history=history))
        raise RecoveryRequiredError(
            "An interrupted install could not be fully rolled back. "
            f"Pending: {'; '.join(problems[:5])}. Inspect {store.base_dir}."
        )
    record.status = "uninstalled"
    record.progress.phase = "rolled_back"
    record.progress.last_error = "interrupted install rolled back"
    record.completed_at = utc_now()
    record.updated_at = utc_now()
    store.save(StoreState(installation=record, history=history))


def _perform_install(
    bundle: Bundle,
    checkout: Checkout,
    store: Store,
    plan: InstallPlan,
    previous: Optional[Installation],
) -> InstallResult:
    installation_id = new_identifier()
    for _ in range(5):
        if not store.install_dir(installation_id).exists():
            break
        installation_id = new_identifier()
    else:
        raise InstallationError("Could not allocate a unique installation id")

    backup_root: Optional[Path] = None
    state_saved = False
    try:
        backup_root, backup_manifest = create_backup(
            store, checkout, installation_id, plan, bundle.fingerprint
        )
        record = _record_from_plan(
            checkout, bundle, installation_id, plan, backup_root, backup_manifest
        )
        previous_state = store.load()
        history = list(previous_state.history) if previous_state else []
        state = StoreState(installation=record, history=history)
        store.push_history(state, previous)
        store.save(state)
        state_saved = True
    except Exception:
        if not state_saved:
            _cleanup_unreferenced_install_dir(store, installation_id)
        raise

    try:
        _write_plan(store, checkout, state, plan)
    except BaseException as exc:
        try:
            backup = load_backup(store, record)
            problems = _rollback(store, checkout, record, backup)
        except Exception as rollback_exc:
            problems = [f"backup or rollback failed: {rollback_exc}"]
        if problems:
            record.status = "recovery_required"
            record.progress.phase = "recovery_required"
            record.progress.last_error = str(exc)
            record.completed_at = utc_now()
            record.updated_at = utc_now()
            try:
                store.save(state)
            except Exception:
                pass
            raise RecoveryRequiredError(
                "Installation failed and automatic rollback was incomplete. "
                f"Pending: {'; '.join(problems[:5])}. Backup: {record.backup_path}. "
                f"Inspect {store.base_dir} before retrying."
            ) from exc
        record.status = "uninstalled"
        record.progress.phase = "rolled_back"
        record.progress.last_error = str(exc)
        record.completed_at = utc_now()
        record.updated_at = utc_now()
        try:
            store.save(state)
        except Exception:
            pass
        raise InstallationError(
            f"Installation failed: {exc}. All managed files were restored from the "
            f"pre-install backup at {record.backup_path}."
        ) from exc

    record.status = "installed"
    record.progress.phase = "complete"
    record.progress.last_error = None
    record.completed_at = utc_now()
    record.updated_at = utc_now()
    store.save(state)
    return InstallResult(
        outcome="installed",
        installation_id=record.installation_id,
        backup_path=record.backup_path,
        added=len(plan.added),
        updated=len(plan.updated),
        preserved_edits=list(plan.preserved_edits),
    )


def _recovery_message(command: str, outcome: str) -> str:
    if outcome == "install":
        return (
            "Recovered an interrupted install and restored the original files. "
            "No new install was performed; re-run the install command."
        )
    return (
        "Completed an interrupted uninstall first (original files are restored). "
        "No new install was performed; re-run the install command."
    )


def _already_installed(
    record: Installation,
    checkout: Checkout,
    bundle: Bundle,
    dry_run: bool,
) -> InstallResult:
    comparison = compare_installed(record, checkout.root)
    notes = []
    if dry_run:
        notes.append("Dry run: the package is already installed; no files would change.")
    else:
        notes.append("The package is already installed; no files were changed.")
    return InstallResult(
        outcome="already-installed",
        installation_id=record.installation_id,
        backup_path=record.backup_path,
        modified_since_install=comparison.modified + comparison.mode_changed,
        missing_since_install=comparison.missing,
        unexpected_paths=comparison.unexpected,
        notes=notes,
    )


def install(bundle_root: Path | str, source: Path | str, dry_run: bool = False) -> InstallResult:
    bundle = load_bundle(bundle_root)
    checkout = resolve_checkout(source)
    store = Store(checkout)

    if dry_run:
        state = store.load()
        record = state.installation if state else None
        if record and record.status == "recovery_required":
            raise RecoveryRequiredError(
                f"The installation is in recovery_required state. See {store.base_dir}."
            )
        if record and record.status in ("installing", "uninstalling"):
            return InstallResult(
                outcome="dry-run",
                installation_id=record.installation_id,
                backup_path=record.backup_path,
                notes=[
                    "An interrupted operation is recorded. A real install would first "
                    "reconcile it, then stop and ask you to re-run install.",
                    "No files would be changed by this dry run.",
                ],
            )
        if record and record.status == "installed":
            if record.package_fingerprint != bundle.fingerprint:
                raise InstallationError(
                    "A different package version is already installed "
                    f"({record.installation_id}). Uninstall it first."
                )
            return _already_installed(record, checkout, bundle, dry_run=True)
        if checkout.head != bundle.base_commit:
            raise InstallationError(
                f"Unsupported Orca checkout: HEAD is {checkout.head}, but the bundle "
                f"requires {bundle.base_commit}. Check out the supported base commit first."
            )
        plan = build_install_plan(checkout, bundle)
        return InstallResult(
            outcome="dry-run",
            added=len(plan.added),
            updated=len(plan.updated),
            preserved_edits=list(plan.preserved_edits),
            notes=[
                "Dry run: no files, backups, state, or locks were created.",
                f"Would write {len(plan.files)} managed files "
                f"({len(plan.updated)} updated, {len(plan.added)} added).",
                "Would create a verified backup under "
                f"{store.base_dir}/<installation-id>/backup before writing.",
                "Would create directories: "
                + (", ".join(plan.created_directories) if plan.created_directories else "none"),
            ],
        )

    with InstallationLock(store, "install"):
        state = store.load()
        record = state.installation if state else None
        if record and record.status == "recovery_required":
            raise RecoveryRequiredError(
                f"The installation is in recovery_required state. See {store.base_dir}."
            )
        if record and record.status in ("installing", "uninstalling"):
            from .recovery import reconcile_locked

            outcome = reconcile_locked(store, checkout, "install")
            raise InterruptedOperationError(_recovery_message("install", outcome or "install"))
        if record and record.status == "installed":
            if record.package_fingerprint != bundle.fingerprint:
                raise InstallationError(
                    "A different package version is already installed "
                    f"({record.installation_id}). Uninstall it first; the first backup "
                    "is never overwritten."
                )
            return _already_installed(record, checkout, bundle, dry_run=False)

        checkout = resolve_checkout(source)
        if checkout.head != bundle.base_commit:
            raise InstallationError(
                f"Unsupported Orca checkout: HEAD is {checkout.head}, but the bundle "
                f"requires {bundle.base_commit}. Check out the supported base commit first."
            )
        plan = build_install_plan(checkout, bundle)
        return _perform_install(bundle, checkout, store, plan, record)
