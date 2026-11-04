"""Versioned installation journal stored under the checkout's Git directory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import json
import os
import re
import secrets
import tempfile

from .errors import PathSafetyError, StateError
from .gitutil import Checkout
from .paths import fsync_directory, normalize_relative_path

BACKUP_DIR_NAME = "orca-advanced-orchestration"
STATE_FORMAT_VERSION = 1
STATE_FILE_NAME = "state.json"
LOCK_FILE_NAME = "installation.lock"
STATUSES = (
    "installing",
    "installed",
    "updating",
    "uninstalling",
    "uninstalled",
    "recovery_required",
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_identifier() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StateError(message)


def _string(value: object, label: str) -> str:
    _require(isinstance(value, str) and bool(value), f"Installation record '{label}' is invalid")
    return value


def _optional_int(value: object, label: str) -> Optional[int]:
    if value is None:
        return None
    _require(isinstance(value, int), f"Installation record '{label}' must be an integer")
    return value


def _relative(value: object, label: str) -> str:
    try:
        return normalize_relative_path(value, label)
    except PathSafetyError as exc:
        raise StateError(str(exc)) from exc


@dataclass
class FileRecord:
    path: str
    original_existed: bool
    original_sha256: Optional[str]
    original_size: Optional[int]
    original_mode: Optional[int]
    installed_sha256: str
    installed_size: int
    installed_mode: int

    def to_dict(self) -> Dict:
        return {
            "path": self.path,
            "original": {
                "existed": self.original_existed,
                "sha256": self.original_sha256,
                "size": self.original_size,
                "mode": self.original_mode,
            },
            "installed": {
                "sha256": self.installed_sha256,
                "size": self.installed_size,
                "mode": self.installed_mode,
            },
        }

    @classmethod
    def from_dict(cls, data: object, index: int) -> "FileRecord":
        _require(isinstance(data, dict), f"managedFiles[{index}] must be an object")
        path = _relative(data.get("path"), f"managedFiles[{index}].path")
        original = data.get("original")
        installed = data.get("installed")
        _require(isinstance(original, dict), f"managedFiles[{index}].original is invalid")
        _require(isinstance(installed, dict), f"managedFiles[{index}].installed is invalid")
        existed = original.get("existed")
        _require(isinstance(existed, bool), f"managedFiles[{index}].original.existed is invalid")
        original_sha = original.get("sha256")
        original_size = _optional_int(original.get("size"), f"managedFiles[{index}].original.size")
        original_mode = _optional_int(
            original.get("mode"), f"managedFiles[{index}].original.mode"
        )
        if existed:
            _require(
                isinstance(original_sha, str) and bool(_SHA_RE.fullmatch(original_sha)),
                f"managedFiles[{index}].original.sha256 is invalid",
            )
            _require(
                original_size is not None and original_size >= 0,
                f"managedFiles[{index}].original.size is invalid",
            )
            _require(original_mode is not None, f"managedFiles[{index}].original.mode is invalid")
        else:
            _require(
                original_sha is None and original_size is None and original_mode is None,
                f"managedFiles[{index}] records content for a file that did not exist",
            )
        installed_sha = installed.get("sha256")
        _require(
            isinstance(installed_sha, str) and bool(_SHA_RE.fullmatch(installed_sha)),
            f"managedFiles[{index}].installed.sha256 is invalid",
        )
        installed_size = _optional_int(
            installed.get("size"), f"managedFiles[{index}].installed.size"
        )
        _require(
            installed_size is not None and installed_size >= 0,
            f"managedFiles[{index}].installed.size is invalid",
        )
        installed_mode = _optional_int(
            installed.get("mode"), f"managedFiles[{index}].installed.mode"
        )
        _require(installed_mode is not None, f"managedFiles[{index}].installed.mode is invalid")
        return cls(
            path=path,
            original_existed=existed,
            original_sha256=original_sha,
            original_size=original_size,
            original_mode=original_mode,
            installed_sha256=installed_sha,
            installed_size=installed_size,
            installed_mode=installed_mode,
        )


@dataclass
class Progress:
    phase: str = "pending"
    completed_paths: List[str] = field(default_factory=list)
    restored_paths: List[str] = field(default_factory=list)
    last_error: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "phase": self.phase,
            "completedPaths": list(self.completed_paths),
            "restoredPaths": list(self.restored_paths),
            "lastError": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: object) -> "Progress":
        if data is None:
            return cls()
        _require(isinstance(data, dict), "Installation record progress is invalid")
        completed = data.get("completedPaths", [])
        restored = data.get("restoredPaths", [])
        _require(isinstance(completed, list) and all(isinstance(x, str) for x in completed),
                 "Installation record progress.completedPaths is invalid")
        _require(isinstance(restored, list) and all(isinstance(x, str) for x in restored),
                 "Installation record progress.restoredPaths is invalid")
        last_error = data.get("lastError")
        _require(last_error is None or isinstance(last_error, str),
                 "Installation record progress.lastError is invalid")
        return cls(
            phase=str(data.get("phase", "pending")),
            completed_paths=list(completed),
            restored_paths=list(restored),
            last_error=last_error,
        )


@dataclass
class Installation:
    installation_id: str
    status: str
    created_at: str
    updated_at: str
    target_root: str
    target_git_dir: str
    head_at_install: str
    package_base_commit: str
    package_implementation_commit: Optional[str]
    package_fingerprint: str
    package_version: Optional[str]
    backup_path: str
    backup_manifest_path: str
    recovery_archives: List[str]
    created_directories: List[str]
    files: List[FileRecord]
    progress: Progress
    packs: List[str] = field(default_factory=list)
    completed_at: Optional[str] = None
    update_id: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "installationId": self.installation_id,
            "status": self.status,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "completedAt": self.completed_at,
            "target": {
                "root": self.target_root,
                "gitDir": self.target_git_dir,
                "headAtInstall": self.head_at_install,
            },
            "package": {
                "baseCommit": self.package_base_commit,
                "implementationCommit": self.package_implementation_commit,
                "fingerprint": self.package_fingerprint,
                "version": self.package_version,
                "fileCount": len(self.files),
                "packs": list(self.packs),
            },
            "backup": {
                "path": self.backup_path,
                "manifestPath": self.backup_manifest_path,
            },
            "recoveryArchives": list(self.recovery_archives),
            "createdDirectories": list(self.created_directories),
            "managedFiles": [item.to_dict() for item in self.files],
            "progress": self.progress.to_dict(),
            "updateId": self.update_id,
        }

    @classmethod
    def from_dict(cls, data: object) -> "Installation":
        _require(isinstance(data, dict), "Installation record must be an object")
        installation_id = _string(data.get("installationId"), "installationId")
        _require(bool(_ID_RE.fullmatch(installation_id)),
                 "Installation record installationId is invalid")
        status = _string(data.get("status"), "status")
        _require(status in STATUSES, f"Installation record has unknown status: {status}")
        target = data.get("target")
        package = data.get("package")
        backup = data.get("backup")
        _require(isinstance(target, dict), "Installation record target is invalid")
        _require(isinstance(package, dict), "Installation record package is invalid")
        _require(isinstance(backup, dict), "Installation record backup is invalid")
        fingerprint = _string(package.get("fingerprint"), "package.fingerprint")
        _require(bool(_SHA_RE.fullmatch(fingerprint)),
                 "Installation record package.fingerprint is invalid")
        raw_files = data.get("managedFiles")
        _require(isinstance(raw_files, list) and bool(raw_files),
                 "Installation record managedFiles is invalid")
        files = [FileRecord.from_dict(entry, index) for index, entry in enumerate(raw_files)]
        _require(len({item.path for item in files}) == len(files),
                 "Installation record lists a managed path more than once")
        _require(len({item.path.casefold() for item in files}) == len(files),
                 "Installation record contains case-colliding managed paths")
        created = data.get("createdDirectories", [])
        _require(isinstance(created, list), "Installation record createdDirectories is invalid")
        created_dirs = [
            _relative(item, "createdDirectories[]") for item in created
        ]
        archives = data.get("recoveryArchives", [])
        _require(isinstance(archives, list) and all(isinstance(x, str) for x in archives),
                 "Installation record recoveryArchives is invalid")
        completed_at = data.get("completedAt")
        _require(completed_at is None or isinstance(completed_at, str),
                 "Installation record completedAt is invalid")
        implementation = package.get("implementationCommit")
        _require(implementation is None or isinstance(implementation, str),
                 "Installation record package.implementationCommit is invalid")
        package_version = package.get("version")
        _require(package_version is None or isinstance(package_version, str),
                 "Installation record package.version is invalid")
        update_id = data.get("updateId")
        _require(update_id is None or isinstance(update_id, str),
                 "Installation record updateId is invalid")
        _require(update_id is None or bool(_ID_RE.fullmatch(update_id)),
                 "Installation record updateId is invalid")
        raw_packs = package.get("packs", [])
        _require(
            isinstance(raw_packs, list) and all(isinstance(item, str) and item for item in raw_packs),
            "Installation record package.packs is invalid",
        )
        _require(len(set(raw_packs)) == len(raw_packs),
                 "Installation record package.packs lists a pack more than once")
        return cls(
            installation_id=installation_id,
            status=status,
            created_at=_string(data.get("createdAt"), "createdAt"),
            updated_at=_string(data.get("updatedAt"), "updatedAt"),
            target_root=_string(target.get("root"), "target.root"),
            target_git_dir=_string(target.get("gitDir"), "target.gitDir"),
            head_at_install=_string(target.get("headAtInstall"), "target.headAtInstall"),
            package_base_commit=_string(package.get("baseCommit"), "package.baseCommit"),
            package_implementation_commit=implementation,
            package_fingerprint=fingerprint,
            package_version=package_version,
            backup_path=_string(backup.get("path"), "backup.path"),
            backup_manifest_path=_string(backup.get("manifestPath"), "backup.manifestPath"),
            recovery_archives=list(archives),
            created_directories=created_dirs,
            files=files,
            progress=Progress.from_dict(data.get("progress")),
            packs=list(raw_packs),
            completed_at=completed_at,
            update_id=update_id,
        )


@dataclass
class StoreState:
    installation: Optional[Installation]
    history: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "formatVersion": STATE_FORMAT_VERSION,
            "installation": self.installation.to_dict() if self.installation else None,
            "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, data: object) -> "StoreState":
        _require(isinstance(data, dict), "Installation state must be a JSON object")
        _require(
            data.get("formatVersion") == STATE_FORMAT_VERSION,
            f"Unsupported installation state formatVersion: {data.get('formatVersion')!r}",
        )
        installation_data = data.get("installation")
        installation = (
            Installation.from_dict(installation_data) if installation_data is not None else None
        )
        history = data.get("history", [])
        _require(isinstance(history, list) and all(isinstance(item, dict) for item in history),
                 "Installation state history is invalid")
        return cls(installation=installation, history=list(history))


class Store:
    def __init__(self, checkout: Checkout):
        self.checkout = checkout
        self.base_dir = checkout.git_dir / BACKUP_DIR_NAME
        self.state_path = self.base_dir / STATE_FILE_NAME
        self.lock_path = self.base_dir / LOCK_FILE_NAME

    def load(self) -> Optional[StoreState]:
        if not self.state_path.exists():
            return None
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise StateError(f"Could not read installation state {self.state_path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise StateError(
                f"Installation state is not valid JSON ({self.state_path}): {exc}"
            ) from exc
        try:
            return StoreState.from_dict(raw)
        except StateError as exc:
            raise StateError(f"Installation state is invalid ({self.state_path}): {exc}") from exc

    def require_state(self) -> StoreState:
        state = self.load()
        if state is None or state.installation is None:
            raise StateError(f"No installation record was found under {self.base_dir}")
        return state

    def save(self, state: StoreState) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")
        fd, temp_name = tempfile.mkstemp(
            prefix=".state-", suffix=".tmp", dir=self.base_dir
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.write(b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.state_path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
        fsync_directory(self.base_dir)

    def install_dir(self, installation_id: str) -> Path:
        return self.base_dir / installation_id

    def backup_dir(self, installation_id: str) -> Path:
        return self.install_dir(installation_id) / "backup"

    def recovery_root(self, installation_id: str) -> Path:
        return self.install_dir(installation_id) / "recovery"

    def push_history(self, state: StoreState, completed: Optional[Installation]) -> None:
        if completed is None:
            return
        state.history.append(
            {
                "installationId": completed.installation_id,
                "status": completed.status,
                "createdAt": completed.created_at,
                "completedAt": completed.completed_at,
                "backupPath": completed.backup_path,
                "packageFingerprint": completed.package_fingerprint,
            }
        )
