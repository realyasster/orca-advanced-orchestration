"""Verified recovery archives for content that would otherwise be discarded."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import json

from .errors import InstallationError
from .paths import (
    assert_safe_destination,
    atomic_write_bytes,
    read_regular_bytes,
    rel_to_os,
    sha256_bytes,
)
from .store import Store, new_identifier, utc_now

ARCHIVE_FORMAT_VERSION = 1


@dataclass(frozen=True)
class ArchiveEntry:
    path: str
    reason: str
    missing: bool
    sha256: Optional[str]
    size: Optional[int]
    mode: Optional[int]


def write_recovery_archive(
    store: Store,
    installation_id: str,
    root: Path,
    entries: List[ArchiveEntry],
) -> Optional[Path]:
    """Write and verify an archive before the caller mutates any target file."""

    if not entries:
        return None
    archive_dir = store.recovery_root(installation_id) / new_identifier()
    archive_dir.mkdir(parents=True)
    manifest_entries: List[Dict] = []
    for entry in entries:
        if entry.missing:
            manifest_entries.append(
                {
                    "path": entry.path,
                    "reason": entry.reason,
                    "sha256": None,
                    "size": None,
                    "mode": None,
                    "archivedFile": None,
                }
            )
            continue
        target = rel_to_os(root, entry.path)
        assert_safe_destination(root, entry.path)
        data, mode = read_regular_bytes(target)
        digest = sha256_bytes(data)
        if digest != entry.sha256 or len(data) != entry.size:
            raise InstallationError(
                f"'{entry.path}' changed while preparing the recovery archive. "
                "No target file was changed; retry."
            )
        archive_rel = f"files/{entry.path}"
        archive_file = rel_to_os(archive_dir, archive_rel)
        archive_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(archive_file, data, mode)
        if sha256_bytes(archive_file.read_bytes()) != digest:
            raise InstallationError(f"Recovery archive verification failed: {archive_file}")
        manifest_entries.append(
            {
                "path": entry.path,
                "reason": entry.reason,
                "sha256": digest,
                "size": len(data),
                "mode": mode,
                "archivedFile": archive_rel,
            }
        )

    manifest = {
        "formatVersion": ARCHIVE_FORMAT_VERSION,
        "installationId": installation_id,
        "createdAt": utc_now(),
        "target": {"root": str(root)},
        "reason": "Files that did not match the recorded original or installed content",
        "entries": manifest_entries,
    }
    manifest_path = archive_dir / "manifest.json"
    atomic_write_bytes(
        manifest_path,
        (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        None,
    )
    # Verify the archive before the caller restores or deletes anything.
    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in loaded["entries"]:
        if entry["archivedFile"] is None:
            continue
        archive_file = rel_to_os(archive_dir, entry["archivedFile"])
        if not archive_file.is_file():
            raise InstallationError(f"Recovery archive file is missing: {archive_file}")
        if sha256_bytes(archive_file.read_bytes()) != entry["sha256"]:
            raise InstallationError(f"Recovery archive verification failed: {archive_file}")
    return archive_dir
