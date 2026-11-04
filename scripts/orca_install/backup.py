"""Create, verify, and read the pre-install byte-for-byte backup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict
import json
import os
import shutil

from .errors import InstallationError, StateError
from .paths import (
    assert_safe_destination,
    atomic_write_bytes,
    is_link_or_junction,
    normalize_relative_path,
    read_regular_bytes,
    rel_to_os,
    sha256_bytes,
    same_path,
)
from .planner import InstallPlan
from .store import Installation, Store, utc_now

BACKUP_FORMAT_VERSION = 1
BACKUP_MANIFEST_NAME = "manifest.json"


@dataclass
class LoadedBackup:
    root: Path
    manifest: Dict
    entries: Dict[str, Dict]

    def read(self, rel: str) -> tuple[bytes, int]:
        entry = self.entries[rel]
        if not entry["existed"]:
            raise StateError(f"Backup record says '{rel}' did not exist; it has no bytes")
        backup_file = rel_to_os(self.root, entry["backupFile"])
        assert_safe_destination(self.root, entry["backupFile"])
        data, _ = read_regular_bytes(backup_file)
        if sha256_bytes(data) != entry["sha256"] or len(data) != entry["size"]:
            raise StateError(
                f"Backup file for '{rel}' failed verification: {backup_file}. "
                "No target file was changed."
            )
        return data, int(entry["mode"])


def _backup_manifest(
    installation_id: str,
    checkout,
    plan: InstallPlan,
    bundle_fingerprint: str,
) -> Dict:
    entries = []
    for item in plan.files:
        entry = {
            "path": item.path,
            "existed": item.original_existed,
            "sha256": item.original_sha256,
            "size": item.original_size,
            "mode": item.original_mode,
            "backupFile": f"files/{item.path}" if item.original_existed else None,
        }
        entries.append(entry)
    return {
        "formatVersion": BACKUP_FORMAT_VERSION,
        "installationId": installation_id,
        "createdAt": utc_now(),
        "target": {"root": str(checkout.root), "gitDir": str(checkout.git_dir)},
        "packageFingerprint": bundle_fingerprint,
        "files": entries,
    }


def create_backup(
    store: Store,
    checkout,
    installation_id: str,
    plan: InstallPlan,
    bundle_fingerprint: str,
) -> tuple[Path, Path]:
    """Write and verify the backup before any target file is modified.

    The current target bytes are read again and compared with the values used
    while planning, so a concurrent edit cannot silently become the "original".
    """

    backup_root = store.backup_dir(installation_id)
    if backup_root.exists():
        raise InstallationError(f"Backup directory already exists: {backup_root}")
    backup_root.mkdir(parents=True)
    try:
        for item in plan.files:
            if not item.original_existed:
                continue
            assert_safe_destination(checkout.root, item.path)
            target = rel_to_os(checkout.root, item.path)
            data, mode = read_regular_bytes(target)
            if sha256_bytes(data) != item.original_sha256 or len(data) != item.original_size:
                raise InstallationError(
                    f"'{item.path}' changed while preparing the installation. "
                    "No target file was changed; retry."
                )
            if mode != item.original_mode:
                raise InstallationError(
                    f"Permissions of '{item.path}' changed while preparing the installation. "
                    "No target file was changed; retry."
                )
            backup_file = rel_to_os(backup_root, f"files/{item.path}")
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(backup_file, data, 0o600 if os.name != "nt" else None)
        manifest = _backup_manifest(installation_id, checkout, plan, bundle_fingerprint)
        manifest_path = backup_root / BACKUP_MANIFEST_NAME
        atomic_write_bytes(
            manifest_path,
            (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
            None,
        )

        # Verify every backup byte and the manifest before returning.
        for entry in manifest["files"]:
            if not entry["existed"]:
                continue
            backup_file = rel_to_os(backup_root, entry["backupFile"])
            if is_link_or_junction(backup_file) or not backup_file.is_file():
                raise InstallationError(f"Backup file is missing or unsafe: {backup_file}")
            data = backup_file.read_bytes()
            if sha256_bytes(data) != entry["sha256"] or len(data) != entry["size"]:
                raise InstallationError(f"Backup verification failed: {backup_file}")
        return backup_root, manifest_path
    except Exception:
        # No state record references this directory yet; the caller removes it.
        raise


def write_carried_backup(
    store: Store,
    checkout,
    installation_id: str,
    bundle_fingerprint: str,
    entries,
    directory_name: str,
    retired_entries=None,
) -> tuple[Path, Path]:
    """Write a verified original backup from explicit entries.

    Updates reuse the original bytes from the first backup and add entries for
    newly managed paths. The first backup directory itself is never modified.
    """

    if (
        not directory_name
        or directory_name in (".", "..")
        or "/" in directory_name
        or "\\" in directory_name
    ):
        raise InstallationError(f"Invalid backup directory name: {directory_name!r}")
    backup_root = store.install_dir(installation_id) / directory_name
    if backup_root.exists():
        raise InstallationError(f"Backup directory already exists: {backup_root}")
    backup_root.mkdir(parents=True)
    try:
        prepared = []
        seen = set()
        for entry in entries:
            rel = normalize_relative_path(entry["path"], "backup path")
            if rel in seen:
                raise InstallationError(f"Duplicate backup entry: {rel}")
            seen.add(rel)
            prepared.append((rel, entry))
        manifest_entries = []
        for rel, entry in prepared:
            existed = bool(entry["existed"])
            if existed:
                data = entry["data"]
                if not isinstance(data, bytes):
                    raise InstallationError(f"Backup entry for '{rel}' has no bytes")
                backup_rel = f"files/{rel}"
                backup_file = rel_to_os(backup_root, backup_rel)
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(
                    backup_file, data, 0o600 if os.name != "nt" else None
                )
                manifest_entries.append(
                    {
                        "path": rel,
                        "existed": True,
                        "sha256": sha256_bytes(data),
                        "size": len(data),
                        "mode": int(entry["mode"]),
                        "backupFile": backup_rel,
                    }
                )
            else:
                manifest_entries.append(
                    {
                        "path": rel,
                        "existed": False,
                        "sha256": None,
                        "size": None,
                        "mode": None,
                        "backupFile": None,
                    }
                )
        retired_manifest = []
        seen_retired = set()
        for entry in retired_entries or []:
            rel = normalize_relative_path(entry["path"], "retired backup path")
            if rel in seen_retired:
                raise InstallationError(f"Duplicate retired backup entry: {rel}")
            seen_retired.add(rel)
            if bool(entry["existed"]):
                data = entry["data"]
                if not isinstance(data, bytes):
                    raise InstallationError(f"Retired backup entry for '{rel}' has no bytes")
                backup_rel = f"retired/{rel}"
                backup_file = rel_to_os(backup_root, backup_rel)
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(
                    backup_file, data, 0o600 if os.name != "nt" else None
                )
                retired_manifest.append(
                    {
                        "path": rel,
                        "existed": True,
                        "sha256": sha256_bytes(data),
                        "size": len(data),
                        "mode": int(entry["mode"]),
                        "backupFile": backup_rel,
                    }
                )
            else:
                retired_manifest.append(
                    {
                        "path": rel,
                        "existed": False,
                        "sha256": None,
                        "size": None,
                        "mode": None,
                        "backupFile": None,
                    }
                )
        manifest = {
            "formatVersion": BACKUP_FORMAT_VERSION,
            "installationId": installation_id,
            "createdAt": utc_now(),
            "target": {"root": str(checkout.root), "gitDir": str(checkout.git_dir)},
            "packageFingerprint": bundle_fingerprint,
            "files": manifest_entries,
            "retiredEntries": retired_manifest,
        }
        manifest_path = backup_root / BACKUP_MANIFEST_NAME
        atomic_write_bytes(
            manifest_path,
            (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
            None,
        )
        for entry in manifest_entries + retired_manifest:
            if not entry["existed"]:
                continue
            backup_file = rel_to_os(backup_root, entry["backupFile"])
            if is_link_or_junction(backup_file) or not backup_file.is_file():
                raise InstallationError(f"Backup file is missing or unsafe: {backup_file}")
            data = backup_file.read_bytes()
            if sha256_bytes(data) != entry["sha256"] or len(data) != entry["size"]:
                raise InstallationError(f"Backup verification failed: {backup_file}")
        return backup_root, manifest_path
    except Exception:
        # No record references this directory yet; remove every partial byte.
        shutil.rmtree(backup_root, ignore_errors=True)
        raise


def load_backup(store: Store, record: Installation) -> LoadedBackup:
    """Load and fully verify the recorded backup. This performs no writes."""

    backup_root = Path(record.backup_path).resolve()
    base = store.base_dir.resolve()
    try:
        backup_root.relative_to(base)
    except ValueError as exc:
        raise StateError(
            f"Recorded backup path is outside the installation data directory: {backup_root}"
        ) from exc
    if not backup_root.is_dir():
        raise StateError(f"Backup directory is missing: {backup_root}")
    manifest_path = Path(record.backup_manifest_path).resolve()
    try:
        manifest_path.relative_to(backup_root)
    except ValueError as exc:
        raise StateError(f"Backup manifest path is outside the backup directory: {manifest_path}") from exc
    if not manifest_path.is_file():
        raise StateError(f"Backup manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"Backup manifest is unreadable ({manifest_path}): {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("formatVersion") != BACKUP_FORMAT_VERSION:
        raise StateError(f"Backup manifest has an unsupported format: {manifest_path}")
    if manifest.get("installationId") != record.installation_id:
        raise StateError("Backup manifest belongs to a different installation id")
    if manifest.get("packageFingerprint") != record.package_fingerprint:
        raise StateError("Backup manifest belongs to a different package version")
    target = manifest.get("target")
    if not isinstance(target, dict):
        raise StateError("Backup manifest target is invalid")
    if not same_path(target.get("root", ""), record.target_root) or not same_path(
        target.get("gitDir", ""), record.target_git_dir
    ):
        raise StateError("Backup manifest target does not match the installation record")
    raw_entries = manifest.get("files")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise StateError("Backup manifest has no file entries")
    entries: Dict[str, Dict] = {}
    for index, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            raise StateError(f"Backup manifest files[{index}] is invalid")
        try:
            rel = normalize_relative_path(entry.get("path"), f"backup.files[{index}].path")
        except Exception as exc:
            raise StateError(f"Backup manifest has an unsafe path: {exc}") from exc
        if rel in entries:
            raise StateError(f"Backup manifest lists '{rel}' more than once")
        existed = entry.get("existed")
        if not isinstance(existed, bool):
            raise StateError(f"Backup manifest entry for '{rel}' has an invalid existed flag")
        if existed:
            backup_rel = normalize_relative_path(
                entry.get("backupFile"), f"backup.files[{index}].backupFile"
            )
            if not backup_rel.startswith("files/"):
                raise StateError(f"Backup manifest entry for '{rel}' has an unsafe backup path")
            backup_file = rel_to_os(backup_root, backup_rel)
            assert_safe_destination(backup_root, backup_rel)
            if not backup_file.is_file():
                raise StateError(
                    f"Backup file is missing for '{rel}': {backup_file}. "
                    "No target file was changed."
                )
            data, _ = read_regular_bytes(backup_file)
            if sha256_bytes(data) != entry.get("sha256") or len(data) != entry.get("size"):
                raise StateError(
                    f"Backup file for '{rel}' failed verification: {backup_file}. "
                    "No target file was changed."
                )
            entry = dict(entry)
            entry["backupFile"] = backup_rel
        else:
            if entry.get("sha256") is not None or entry.get("size") is not None:
                raise StateError(f"Backup manifest entry for '{rel}' has unexpected content")
        entries[rel] = entry

    record_paths = {item.path: item for item in record.files}
    if set(entries) != set(record_paths):
        raise StateError(
            "Backup manifest file list does not match the installation record. "
            "No target file was changed."
        )
    for rel, item in record_paths.items():
        entry = entries[rel]
        if bool(entry["existed"]) != item.original_existed:
            raise StateError(f"Backup record for '{rel}' disagrees about whether it existed")
        if item.original_existed:
            if (
                entry.get("sha256") != item.original_sha256
                or entry.get("size") != item.original_size
                or entry.get("mode") != item.original_mode
            ):
                raise StateError(f"Backup record for '{rel}' does not match the install record")
    return LoadedBackup(root=backup_root, manifest=manifest, entries=entries)
