"""Prepare install bytes by applying the patch to a scratch copy of local files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import os
import stat
import tempfile

from .bundle import Bundle
from .errors import BundleError, PathSafetyError
from .gitutil import Checkout, apply_patch
from .paths import (
    assert_safe_destination,
    is_link_or_junction,
    read_regular_bytes,
    rel_to_os,
    sha256_bytes,
)


@dataclass(frozen=True)
class PreparedFile:
    path: str
    data: bytes
    mode: int
    sha256: str
    original_existed: bool
    original_sha256: Optional[str]
    original_size: Optional[int]
    original_mode: Optional[int]
    matches_snapshot: bool


@dataclass
class InstallPlan:
    files: List[PreparedFile]
    created_directories: List[str]
    preserved_edits: List[str]

    @property
    def added(self) -> List[str]:
        return [item.path for item in self.files if not item.original_existed]

    @property
    def updated(self) -> List[str]:
        return [item.path for item in self.files if item.original_existed]


def _patch_temp_name(managed_paths: List[str]) -> str:
    """Choose a scratch patch name that cannot collide with a managed path."""

    name = ".orca-ao-bundle.patch"
    while name in managed_paths:
        name += ".patch"
    return name


def _write_scratch_file(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    try:
        os.chmod(path, (mode & 0o777) | stat.S_IWUSR)
    except OSError:
        pass


def _planned_directories(root: Path, files: List[PreparedFile]) -> List[str]:
    planned: List[str] = []
    seen = set()
    for item in files:
        parts = item.path.split("/")[:-1]
        current = root
        for index, part in enumerate(parts):
            rel = "/".join(parts[: index + 1])
            current = current / part
            if is_link_or_junction(current):
                raise PathSafetyError(
                    f"Refusing to create a directory through a symbolic link or junction: "
                    f"{current}"
                )
            if current.exists():
                if not current.is_dir():
                    raise PathSafetyError(
                        f"Refusing to install '{item.path}': parent is not a directory: {current}"
                    )
                continue
            if rel not in seen:
                seen.add(rel)
                planned.append(rel)
    return planned


def build_install_plan(checkout: Checkout, bundle: Bundle) -> InstallPlan:
    """Apply the bundle patch to copies of the current local files.

    The target checkout is only read here. If the patch does not apply exactly,
    the caller receives an error and no target file has been touched.
    """

    root = checkout.root
    prepared: List[PreparedFile] = []
    temp_name = _patch_temp_name(bundle.patch_paths)
    with tempfile.TemporaryDirectory(prefix="orca-ao-apply-") as temp_dir:
        scratch = Path(temp_dir)
        originals = {}
        for rel in bundle.patch_paths:
            assert_safe_destination(root, rel)
            target = rel_to_os(root, rel)
            if target.exists():
                data, mode = read_regular_bytes(target)
                originals[rel] = (sha256_bytes(data), len(data), mode)
                _write_scratch_file(rel_to_os(scratch, rel), data, mode)
            else:
                originals[rel] = None

        patch_file = scratch / temp_name
        patch_file.write_bytes(bundle.patch_bytes)
        apply_patch(patch_file, scratch)

        for bundle_file in bundle.files:
            rel = bundle_file.upstream_path
            applied_path = rel_to_os(scratch, rel)
            if is_link_or_junction(applied_path) or not applied_path.is_file():
                raise BundleError(
                    f"Patch did not produce a regular file for '{rel}'. The bundle is inconsistent."
                )
            data = applied_path.read_bytes()
            digest = sha256_bytes(data)
            applied_mode = stat.S_IMODE(os.stat(applied_path).st_mode)
            original = originals[rel]
            if original is None:
                if digest != bundle_file.sha256:
                    raise BundleError(
                        f"New file '{rel}' does not match the bundle snapshot. "
                        "The patch and snapshot disagree."
                    )
                mode = applied_mode
                prepared.append(
                    PreparedFile(
                        path=rel,
                        data=data,
                        mode=mode,
                        sha256=digest,
                        original_existed=False,
                        original_sha256=None,
                        original_size=None,
                        original_mode=None,
                        matches_snapshot=digest == bundle_file.sha256,
                    )
                )
            else:
                original_sha, original_size, original_mode = original
                prepared.append(
                    PreparedFile(
                        path=rel,
                        data=data,
                        mode=original_mode,
                        sha256=digest,
                        original_existed=True,
                        original_sha256=original_sha,
                        original_size=original_size,
                        original_mode=original_mode,
                        matches_snapshot=digest == bundle_file.sha256,
                    )
                )

    created = _planned_directories(root, prepared)
    preserved = [item.path for item in prepared if item.matches_snapshot is False]
    return InstallPlan(files=prepared, created_directories=created, preserved_edits=preserved)
