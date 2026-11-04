"""Transactional package updates that preserve the first original backup."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import json
import os
import shutil

from .archive import ArchiveEntry, write_recovery_archive
from .backup import LoadedBackup, load_backup, write_carried_backup
from .bundle import Bundle, load_bundle
from .errors import (
    InstallationError,
    InterruptedOperationError,
    RecoveryRequiredError,
    StateError,
)
from .gitutil import Checkout, resolve_checkout
from .installer import compare_installed, verify_installed
from .lock import InstallationLock
from .paths import (
    assert_safe_destination,
    atomic_write_bytes,
    ensure_parent_directories,
    inspect_destination,
    read_regular_bytes,
    rel_to_os,
    remove_empty_directories,
    remove_regular_file,
    same_path,
    sha256_bytes,
)
from .store import (
    FileRecord,
    Installation,
    Progress,
    Store,
    StoreState,
    new_identifier,
    utc_now,
)

SNAPSHOT_FORMAT_VERSION = 1
UPDATE_PLAN_FORMAT_VERSION = 1


@dataclass
class UpdateResult:
    outcome: str
    installation_id: Optional[str] = None
    backup_path: Optional[str] = None
    from_version: Optional[str] = None
    to_version: Optional[str] = None
    added: int = 0
    updated: int = 0
    removed: int = 0
    notes: List[str] = field(default_factory=list)


@dataclass
class PlannedFile:
    path: str
    data: bytes
    sha256: str
    mode: int
    original_existed: bool
    original_sha256: Optional[str]
    original_size: Optional[int]
    original_mode: Optional[int]


@dataclass
class UpdatePlan:
    files: List[PlannedFile]
    removed: List[FileRecord]
    original_entries: List[Dict]
    retired_entries: List[Dict]
    previous_entries: Dict[str, Dict]
    created_directories: List[str]

    @property
    def added(self) -> List[PlannedFile]:
        return [item for item in self.files if not item.original_existed]

    @property
    def updated(self) -> List[PlannedFile]:
        return [item for item in self.files if item.original_existed]


def _update_dir(store: Store, record: Installation, update_id: str) -> Path:
    return store.install_dir(record.installation_id) / "updates" / update_id


def _cleanup_update_artifacts(
    store: Store,
    installation_id: str,
    update_id: str,
    include_backup: bool,
) -> None:
    """Remove temporary update journals and, after rollback, their backup."""

    install_dir = store.install_dir(installation_id)
    shutil.rmtree(install_dir / "updates" / update_id, ignore_errors=True)
    updates_root = install_dir / "updates"
    try:
        updates_root.rmdir()
    except OSError:
        pass
    if include_backup:
        shutil.rmtree(install_dir / f"backup-{update_id}", ignore_errors=True)


def _require_identity(record: Installation, checkout: Checkout) -> None:
    if not same_path(record.target_root, checkout.root) or not same_path(
        record.target_git_dir, checkout.git_dir
    ):
        raise StateError(
            "The installation record belongs to a different checkout "
            f"({record.target_root}). Refusing to update files here."
        )


def _inspect_target(root: Path, rel: str) -> Dict:
    assert_safe_destination(root, rel)
    path = rel_to_os(root, rel)
    state = inspect_destination(path, with_hash=True)
    if state.exists and not state.is_file:
        raise InstallationError(
            f"Refusing to update '{rel}': expected a regular file, found another type."
        )
    return {
        "exists": state.exists,
        "sha256": state.sha256,
        "size": state.size,
        "mode": state.mode,
    }


def _build_plan(
    checkout: Checkout, bundle: Bundle, record: Installation, backup: LoadedBackup
) -> UpdatePlan:
    root = checkout.root
    old = {item.path: item for item in record.files}
    new_paths = {item.upstream_path for item in bundle.files}
    previous: Dict[str, Dict] = {}
    originals: List[Dict] = []
    files: List[PlannedFile] = []
    created: List[str] = []

    def inspect_union(rel: str) -> Dict:
        state = _inspect_target(root, rel)
        if state["exists"]:
            data, mode = read_regular_bytes(rel_to_os(root, rel))
            if sha256_bytes(data) != state["sha256"] or len(data) != state["size"]:
                raise InstallationError(
                    f"'{rel}' changed while preparing the update. No file was changed."
                )
            state = dict(state)
            state["data"] = data
            state["mode"] = mode
        previous[rel] = state
        return state

    for bundle_file in bundle.files:
        rel = bundle_file.upstream_path
        current = inspect_union(rel)
        old_file = old.get(rel)
        if old_file is not None:
            if (
                not current["exists"]
                or current["sha256"] != old_file.installed_sha256
                or current["size"] != old_file.installed_size
            ):
                raise InstallationError(
                    f"'{rel}' was modified after installation. Update refused; no file "
                    "was changed. Revert the local change or uninstall and reinstall."
                )
            mode = old_file.installed_mode
            original = {
                "path": rel,
                "existed": old_file.original_existed,
                "data": None,
                "mode": old_file.original_mode,
            }
            if old_file.original_existed:
                data, original_mode = backup.read(rel)
                original["data"] = data
                original["mode"] = original_mode
            originals.append(original)
        elif current["exists"]:
            # A file that the previous package did not manage. Treat the current
            # bytes as the original so a later uninstall can restore them.
            original = {
                "path": rel,
                "existed": True,
                "data": current["data"],
                "mode": current["mode"],
            }
            originals.append(original)
            mode = current["mode"]
        else:
            original = {"path": rel, "existed": False, "data": None, "mode": None}
            originals.append(original)
            mode = 0o644

        data = bundle_file.data
        digest = sha256_bytes(data)
        if digest != bundle_file.sha256:
            raise InstallationError(
                f"Verified snapshot for '{rel}' changed before the update was written."
            )
        files.append(
            PlannedFile(
                path=rel,
                data=data,
                sha256=digest,
                mode=mode,
                original_existed=bool(original["existed"]),
                original_sha256=sha256_bytes(original["data"])
                if original["existed"]
                else None,
                original_size=len(original["data"]) if original["existed"] else None,
                original_mode=original["mode"] if original["existed"] else None,
            )
        )

    removed = [item for item in record.files if item.path not in new_paths]
    retired = []
    for item in removed:
        current = inspect_union(item.path)
        if (
            not current["exists"]
            or current["sha256"] != item.installed_sha256
            or current["size"] != item.installed_size
        ):
            raise InstallationError(
                f"'{item.path}' was modified after installation. Update refused; "
                "no file was changed."
            )
        if item.original_existed:
            original_data, original_mode = backup.read(item.path)
            retired.append(
                {
                    "path": item.path,
                    "existed": True,
                    "data": original_data,
                    "mode": original_mode,
                }
            )
        else:
            retired.append(
                {"path": item.path, "existed": False, "data": None, "mode": None}
            )

    # Include directories that exist only in the new package so uninstall can
    # remove them later once they are empty.
    for item in files:
        current = root
        parts = item.path.split("/")[:-1]
        for index, part in enumerate(parts):
            current = current / part
            if not current.exists():
                created.append("/".join(parts[: index + 1]))

    return UpdatePlan(
        files=files,
        removed=removed,
        original_entries=originals,
        retired_entries=retired,
        previous_entries=previous,
        created_directories=sorted(set(created)),
    )


def _snapshot_payload(entries: Dict[str, Dict], installation_id: str, update_id: str) -> Dict:
    manifest_entries = []
    for rel in sorted(entries):
        state = entries[rel]
        manifest_entries.append(
            {
                "path": rel,
                "existed": bool(state["exists"]),
                "sha256": state.get("sha256"),
                "size": state.get("size"),
                "mode": state.get("mode"),
                "file": f"files/{rel}" if state["exists"] else None,
            }
        )
    return {
        "formatVersion": SNAPSHOT_FORMAT_VERSION,
        "installationId": installation_id,
        "updateId": update_id,
        "createdAt": utc_now(),
        "entries": manifest_entries,
    }


def _write_previous_snapshot(
    store: Store,
    record: Installation,
    update_id: str,
    plan: UpdatePlan,
    old_record: Dict,
    new_targets: Dict[str, Optional[str]],
) -> Path:
    directory = _update_dir(store, record, update_id)
    directory.mkdir(parents=True)
    snapshot_root = directory / "previous"
    snapshot_root.mkdir()

    for rel, state in plan.previous_entries.items():
        if not state["exists"]:
            continue
        snapshot_rel = f"files/{rel}"
        snapshot_file = rel_to_os(snapshot_root, snapshot_rel)
        snapshot_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(snapshot_file, state["data"], 0o600 if os.name != "nt" else None)

    manifest = _snapshot_payload(plan.previous_entries, record.installation_id, update_id)
    manifest_path = snapshot_root / "manifest.json"
    atomic_write_bytes(
        manifest_path,
        (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        None,
    )
    previous_state_path = directory / "previous-state.json"
    atomic_write_bytes(
        previous_state_path,
        (json.dumps(old_record, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        None,
    )
    new_plan = {
        "formatVersion": UPDATE_PLAN_FORMAT_VERSION,
        "installationId": record.installation_id,
        "updateId": update_id,
        "createdAt": utc_now(),
        "targets": new_targets,
        "createdDirectories": list(plan.created_directories),
    }
    atomic_write_bytes(
        directory / "plan.json",
        (json.dumps(new_plan, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        None,
    )

    # Verify the rollback snapshot before any target file is touched.
    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in loaded["entries"]:
        if entry["file"] is None:
            continue
        archive_file = rel_to_os(snapshot_root, entry["file"])
        if not archive_file.is_file():
            raise InstallationError(f"Update snapshot file is missing: {archive_file}")
        if sha256_bytes(archive_file.read_bytes()) != entry["sha256"]:
            raise InstallationError(f"Update snapshot verification failed: {archive_file}")
    return directory


def _restore_snapshot(store: Store, checkout: Checkout, directory: Path) -> List[str]:
    problems: List[str] = []
    snapshot_root = directory / "previous"
    manifest_path = snapshot_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"rollback snapshot is unreadable: {exc}"]
    for entry in manifest.get("entries", []):
        rel = entry.get("path")
        try:
            assert_safe_destination(checkout.root, rel)
            target = rel_to_os(checkout.root, rel)
            if entry.get("existed"):
                archive_file = rel_to_os(snapshot_root, entry["file"])
                data = archive_file.read_bytes()
                if sha256_bytes(data) != entry["sha256"] or len(data) != entry["size"]:
                    problems.append(f"{rel}: rollback bytes failed verification")
                    continue
                ensure_parent_directories(checkout.root, rel)
                atomic_write_bytes(target, data, int(entry["mode"]))
            else:
                state = inspect_destination(target)
                if state.exists:
                    if state.is_file:
                        remove_regular_file(target)
                    else:
                        problems.append(f"{rel}: refusing to remove an unexpected non-file")
        except Exception as exc:
            problems.append(f"{rel}: {exc}")
    for entry in manifest.get("entries", []):
        rel = entry.get("path")
        if any(problem.startswith(f"{rel}:") for problem in problems):
            continue
        try:
            state = inspect_destination(rel_to_os(checkout.root, rel), with_hash=True)
        except Exception as exc:
            problems.append(f"{rel}: {exc}")
            continue
        if entry.get("existed"):
            if (
                not state.exists
                or not state.is_file
                or state.sha256 != entry.get("sha256")
                or state.size != entry.get("size")
            ):
                problems.append(f"{rel}: rollback content mismatch")
        elif state.exists:
            problems.append(f"{rel}: file appeared during rollback")
    try:
        plan_path = directory / "plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        remove_empty_directories(checkout.root, plan.get("createdDirectories", []))
    except Exception as exc:
        problems.append(f"directory cleanup: {exc}")
    return problems


def _unexpected_entries(directory: Path, root: Path) -> tuple[List[ArchiveEntry], List[str]]:
    entries: List[ArchiveEntry] = []
    problems: List[str] = []
    try:
        plan = json.loads((directory / "plan.json").read_text(encoding="utf-8"))
        snapshot = json.loads(
            (directory / "previous" / "manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"update journal is unreadable: {exc}"]
    previous = {item["path"]: item for item in snapshot.get("entries", [])}
    targets = plan.get("targets", {})
    for rel, target in targets.items():
        try:
            assert_safe_destination(root, rel)
            state = inspect_destination(rel_to_os(root, rel), with_hash=True)
        except Exception as exc:
            problems.append(f"{rel}: {exc}")
            continue
        if state.exists and not state.is_file:
            problems.append(f"{rel}: expected a regular file, found another type")
            continue
        allowed = set()
        prev = previous.get(rel)
        if prev:
            if prev.get("existed"):
                allowed.add(prev.get("sha256"))
            else:
                allowed.add(None)
        if target is not None:
            allowed.add(target)
        if state.exists:
            if state.sha256 not in allowed:
                entries.append(
                    ArchiveEntry(
                        path=rel,
                        reason="unexpected-content-during-update-recovery",
                        missing=False,
                        sha256=state.sha256,
                        size=state.size,
                        mode=state.mode,
                    )
                )
        elif None not in allowed:
            entries.append(
                ArchiveEntry(
                    path=rel,
                    reason="missing-before-update-recovery",
                    missing=True,
                    sha256=None,
                    size=None,
                    mode=None,
                )
            )
    return entries, problems


def _cleanup_removed_directories(
    record: Installation, root: Path, plan: UpdatePlan
) -> None:
    """Drop empty install-created directories that the new package no longer uses."""

    required = set()
    for item in plan.files:
        parts = item.path.split("/")[:-1]
        for index in range(1, len(parts) + 1):
            required.add("/".join(parts[:index]))
    optional = [rel for rel in record.created_directories if rel not in required]
    if not optional:
        return
    retained = set(remove_empty_directories(root, optional))
    record.created_directories = [
        rel
        for rel in record.created_directories
        if rel not in optional or rel in retained
    ]


def _record_after_update(
    old: Installation,
    bundle: Bundle,
    checkout: Checkout,
    files: List[PlannedFile],
    backup_root: Path,
    backup_manifest: Path,
) -> Installation:
    now = utc_now()
    return Installation(
        installation_id=old.installation_id,
        status="installed",
        created_at=old.created_at,
        updated_at=now,
        target_root=str(checkout.root),
        target_git_dir=str(checkout.git_dir),
        head_at_install=checkout.head,
        package_base_commit=bundle.base_commit,
        package_implementation_commit=bundle.implementation_commit,
        package_fingerprint=bundle.fingerprint,
        package_version=bundle.package_version,
        backup_path=str(backup_root),
        backup_manifest_path=str(backup_manifest),
        recovery_archives=list(old.recovery_archives),
        created_directories=list(old.created_directories),
        files=[
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
            for item in files
        ],
        progress=Progress(phase="complete"),
        completed_at=now,
    )


def _save(store: Store, record: Installation) -> None:
    state = store.load()
    history = list(state.history) if state else []
    store.save(StoreState(installation=record, history=history))


def _apply_removed(
    store: Store,
    checkout: Checkout,
    record: Installation,
    plan: UpdatePlan,
    backup: LoadedBackup,
) -> None:
    for item in plan.removed:
        target = rel_to_os(checkout.root, item.path)
        if item.original_existed:
            data, mode = backup.read(item.path)
            ensure_parent_directories(checkout.root, item.path)
            atomic_write_bytes(target, data, mode)
        else:
            remove_regular_file(target)
        record.progress.completed_paths.append(item.path)
        record.updated_at = utc_now()
        _save(store, record)


def _rollback_update(
    store: Store,
    checkout: Checkout,
    record: Installation,
    directory: Path,
    extra_archives: Optional[List[str]] = None,
) -> List[str]:
    problems = _restore_snapshot(store, checkout, directory)
    if problems:
        return problems
    try:
        old_data = json.loads(
            (directory / "previous-state.json").read_text(encoding="utf-8")
        )
        old = Installation.from_dict(old_data)
    except Exception as exc:
        return [f"previous installation record is unreadable: {exc}"]
    for archive in extra_archives or []:
        if archive not in old.recovery_archives:
            old.recovery_archives.append(archive)
    old.status = "installed"
    old.progress.phase = "rolled_back"
    old.progress.last_error = "update failed; previous installed version restored"
    old.updated_at = utc_now()
    old.update_id = None
    try:
        _save(store, old)
    except Exception as exc:
        problems.append(f"could not save the restored record: {exc}")
    if not problems:
        _cleanup_update_artifacts(
            store,
            old.installation_id,
            record.update_id or directory.name,
            include_backup=True,
        )
    return problems


def rollback_interrupted_update(
    store: Store, checkout: Checkout, record: Installation
) -> None:
    """Restore the previous installed version after an interrupted update."""

    _require_identity(record, checkout)
    if not record.update_id:
        record.status = "recovery_required"
        record.progress.phase = "recovery_required"
        record.progress.last_error = "updating state has no update id"
        record.updated_at = utc_now()
        _save(store, record)
        raise RecoveryRequiredError(
            f"The update journal is incomplete. Inspect {store.base_dir} before retrying."
        )
    directory = _update_dir(store, record, record.update_id)
    if not directory.is_dir():
        record.status = "recovery_required"
        record.progress.phase = "recovery_required"
        record.progress.last_error = "update snapshot directory is missing"
        record.updated_at = utc_now()
        _save(store, record)
        raise RecoveryRequiredError(
            f"The update snapshot is missing ({directory}). Inspect {store.base_dir}."
        )

    entries, problems = _unexpected_entries(directory, checkout.root)
    if problems:
        record.status = "recovery_required"
        record.progress.phase = "recovery_required"
        record.progress.last_error = "unexpected target content before update rollback: " + "; ".join(
            problems[:5]
        )
        record.updated_at = utc_now()
        _save(store, record)
        raise RecoveryRequiredError(
            "An interrupted update has unexpected target types; refusing to overwrite them. "
            f"Pending: {'; '.join(problems[:5])}. Inspect {store.base_dir}."
        )
    if entries:
        archive = None
        try:
            archive = write_recovery_archive(
                store, record.installation_id, checkout.root, entries
            )
        except Exception as exc:
            record.status = "recovery_required"
            record.progress.phase = "recovery_required"
            record.progress.last_error = f"update recovery archive failed: {exc}"
            record.updated_at = utc_now()
            _save(store, record)
            raise RecoveryRequiredError(
                "An interrupted update has content that could not be archived safely; "
                f"refusing to roll it back: {exc}. Inspect {store.base_dir}."
            ) from exc
        if archive is not None:
            record.recovery_archives.append(str(archive))

    problems = _rollback_update(
        store,
        checkout,
        record,
        directory,
        [str(archive)] if archive is not None else None,
    )
    if problems:
        record.status = "recovery_required"
        record.progress.phase = "recovery_required"
        record.progress.last_error = "update rollback incomplete: " + "; ".join(problems[:5])
        record.updated_at = utc_now()
        _save(store, record)
        raise RecoveryRequiredError(
            "An interrupted update could not be fully rolled back. "
            f"Pending: {'; '.join(problems[:5])}. Inspect {store.base_dir}."
        )


def _perform_update(
    bundle: Bundle,
    checkout: Checkout,
    store: Store,
    record: Installation,
    plan: UpdatePlan,
    backup: LoadedBackup,
) -> UpdateResult:
    old_record = record.to_dict()
    old_version = record.package_version
    update_id = new_identifier()
    for _ in range(5):
        if not _update_dir(store, record, update_id).exists():
            break
        update_id = new_identifier()
    else:
        raise InstallationError("Could not allocate a unique update id")

    targets: Dict[str, Optional[str]] = {}
    for item in plan.files:
        targets[item.path] = item.sha256
    for item in plan.removed:
        if item.original_existed:
            data, _ = backup.read(item.path)
            targets[item.path] = sha256_bytes(data)
        else:
            targets[item.path] = None
    for rel in plan.previous_entries:
        targets.setdefault(rel, None)

    directory: Optional[Path] = None
    update_path = _update_dir(store, record, update_id)
    try:
        directory = _write_previous_snapshot(
            store, record, update_id, plan, old_record, targets
        )
    except Exception as exc:
        shutil.rmtree(update_path, ignore_errors=True)
        raise InstallationError(f"Could not prepare the update rollback snapshot: {exc}") from exc

    backup_root: Optional[Path] = None
    try:
        backup_root, backup_manifest = write_carried_backup(
            store,
            checkout,
            record.installation_id,
            bundle.fingerprint,
            plan.original_entries,
            f"backup-{update_id}",
            retired_entries=plan.retired_entries,
        )
    except Exception as exc:
        shutil.rmtree(update_path, ignore_errors=True)
        shutil.rmtree(
            store.install_dir(record.installation_id) / f"backup-{update_id}",
            ignore_errors=True,
        )
        raise InstallationError(f"Could not prepare the update backup: {exc}") from exc

    record.status = "updating"
    record.update_id = update_id
    record.progress.phase = "updating"
    record.progress.completed_paths = []
    record.progress.last_error = None
    for rel in plan.created_directories:
        if rel not in record.created_directories:
            record.created_directories.append(rel)
    record.updated_at = utc_now()
    try:
        _save(store, record)
    except Exception as exc:
        shutil.rmtree(update_path, ignore_errors=True)
        shutil.rmtree(
            store.install_dir(record.installation_id) / f"backup-{update_id}",
            ignore_errors=True,
        )
        raise InstallationError(f"Could not write the update journal: {exc}") from exc

    try:
        _apply_removed(store, checkout, record, plan, backup)
        for item in plan.files:
            ensure_parent_directories(checkout.root, item.path, record.created_directories)
            atomic_write_bytes(rel_to_os(checkout.root, item.path), item.data, item.mode)
            record.progress.completed_paths.append(item.path)
            record.updated_at = utc_now()
            _save(store, record)
        _cleanup_removed_directories(record, checkout.root, plan)
        new_record = _record_after_update(
            record, bundle, checkout, plan.files, backup_root, backup_manifest
        )
        problems = verify_installed(new_record, checkout.root)
        if problems:
            raise InstallationError(
                "Update wrote files but post-update verification failed: "
                + "; ".join(problems[:5])
            )
    except BaseException as exc:
        problems = _rollback_update(store, checkout, record, directory)
        if problems:
            record.status = "recovery_required"
            record.progress.phase = "recovery_required"
            record.progress.last_error = str(exc) + " | " + "; ".join(problems[:5])
            record.completed_at = utc_now()
            record.updated_at = utc_now()
            try:
                _save(store, record)
            except Exception:
                pass
            raise RecoveryRequiredError(
                "Update failed and automatic rollback was incomplete. "
                f"Pending: {'; '.join(problems[:5])}. Inspect {store.base_dir}."
            ) from exc
        raise InstallationError(
            f"Update failed: {exc}. The previous installed version was restored."
        ) from exc

    new_record.updated_at = utc_now()
    new_record.completed_at = utc_now()
    _save(store, new_record)
    _cleanup_update_artifacts(
        store, new_record.installation_id, update_id, include_backup=False
    )
    return UpdateResult(
        outcome="updated",
        installation_id=new_record.installation_id,
        backup_path=new_record.backup_path,
        from_version=old_version,
        to_version=bundle.package_version,
        added=len(plan.added),
        updated=len(plan.updated),
        removed=len(plan.removed),
    )


def _check_package(record: Installation, bundle: Bundle, checkout: Checkout) -> List[str]:
    notes: List[str] = []
    if record.package_fingerprint == bundle.fingerprint:
        return notes
    if record.package_version and record.package_version == bundle.package_version:
        raise InstallationError(
            f"Package version {bundle.package_version} is already installed with different "
            "content. Refusing to replace it silently; commit a new package version first."
        )
    if checkout.head != bundle.base_commit:
        raise InstallationError(
            f"Unsupported Orca checkout: HEAD is {checkout.head}, but package "
            f"{bundle.package_version} requires {bundle.base_commit}. The tool never runs "
            "git reset or git checkout automatically. Check out the supported upstream "
            "commit or use a package that supports your checkout."
        )
    if record.package_base_commit != bundle.base_commit:
        raise InstallationError(
            f"The installed package targets Orca commit {record.package_base_commit}, but "
            f"package {bundle.package_version} targets {bundle.base_commit}. Updating "
            "across upstream bases would require an automatic reset/checkout, which this "
            "tool refuses to do. Check out the new upstream base and reinstall explicitly."
        )
    return notes


def update(bundle_root: Path | str, source: Path | str, dry_run: bool = False) -> UpdateResult:
    bundle = load_bundle(bundle_root)
    checkout = resolve_checkout(source)
    store = Store(checkout)

    if dry_run:
        state = store.load()
        record = state.installation if state else None
        if record is None or record.status == "uninstalled":
            raise InstallationError(
                "No active installation was found; use install instead of update."
            )
        if record.status == "recovery_required":
            raise RecoveryRequiredError(
                f"The installation is in recovery_required state. See {store.base_dir}."
            )
        if record.status in ("installing", "uninstalling", "updating"):
            return UpdateResult(
                outcome="dry-run",
                installation_id=record.installation_id,
                from_version=record.package_version,
                to_version=bundle.package_version,
                notes=[
                    "An interrupted operation is recorded. A real update would reconcile "
                    "it first.",
                    "No files would be changed by this dry run.",
                ],
            )
        if record.status != "installed":
            raise InstallationError(f"Cannot update an installation in state {record.status}.")
        _require_identity(record, checkout)
        if record.package_fingerprint == bundle.fingerprint:
            return UpdateResult(
                outcome="no-op",
                installation_id=record.installation_id,
                backup_path=record.backup_path,
                from_version=record.package_version,
                to_version=bundle.package_version,
                notes=["The requested package is already installed; no files would change."],
            )
        notes = _check_package(record, bundle, checkout)
        comparison = compare_installed(record, checkout.root)
        if not comparison.clean:
            raise InstallationError(
                "Local changes were detected; update refused before changing anything: "
                + "; ".join(
                    (comparison.modified + comparison.missing + comparison.unexpected)[:5]
                )
            )
        backup = load_backup(store, record)
        plan = _build_plan(checkout, bundle, record, backup)
        notes.extend(
            [
                "Dry run: no files, backups, locks, or journal entries were created.",
                f"Would update {len(plan.updated)} files, add {len(plan.added)}, and "
                f"remove {len(plan.removed)} from management.",
            ]
        )
        return UpdateResult(
            outcome="dry-run",
            installation_id=record.installation_id,
            backup_path=record.backup_path,
            from_version=record.package_version,
            to_version=bundle.package_version,
            added=len(plan.added),
            updated=len(plan.updated),
            removed=len(plan.removed),
            notes=notes,
        )

    with InstallationLock(store, "update"):
        state = store.load()
        record = state.installation if state else None
        if record is None or record.status == "uninstalled":
            raise InstallationError(
                "No active installation was found; use install instead of update."
            )
        if record.status == "recovery_required":
            raise RecoveryRequiredError(
                f"The installation is in recovery_required state. See {store.base_dir}."
            )
        if record.status in ("installing", "uninstalling", "updating"):
            from .recovery import reconcile_locked

            reconcile_locked(store, checkout, "update")
            raise InterruptedOperationError(
                "Recovered an interrupted operation. Re-run update to continue."
            )
        if record.status != "installed":
            raise InstallationError(f"Cannot update an installation in state {record.status}.")
        _require_identity(record, checkout)
        if record.package_fingerprint == bundle.fingerprint:
            return UpdateResult(
                outcome="no-op",
                installation_id=record.installation_id,
                backup_path=record.backup_path,
                from_version=record.package_version,
                to_version=bundle.package_version,
                notes=["The requested package is already installed; no files were changed."],
            )
        _check_package(record, bundle, checkout)
        comparison = compare_installed(record, checkout.root)
        if not comparison.clean:
            raise InstallationError(
                "Local changes were detected; update refused before changing anything: "
                + "; ".join(
                    (comparison.modified + comparison.missing + comparison.unexpected)[:5]
                )
            )
        backup = load_backup(store, record)
        plan = _build_plan(checkout, bundle, record, backup)
        return _perform_update(bundle, checkout, store, record, plan, backup)
