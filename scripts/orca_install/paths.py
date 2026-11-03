"""Filesystem safety, hashing, modes, and atomic file replacement."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional
import hashlib
import os
import stat
import tempfile

from .errors import PathSafetyError

FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_relative_path(value: object, kind: str = "path") -> str:
    """Validate and normalize a POSIX-style path that must stay relative.

    Backslashes, drive letters, empty segments, and ``..`` segments are rejected
    so the same manifest cannot mean one path on Linux and another on Windows.
    """

    if not isinstance(value, str) or not value:
        raise PathSafetyError(f"Invalid {kind}: expected a non-empty string")
    if "\x00" in value:
        raise PathSafetyError(f"Invalid {kind}: contains a NUL byte")
    if "\\" in value:
        raise PathSafetyError(f"Invalid {kind} (use forward slashes): {value}")
    if value.startswith("/") or value.startswith("//"):
        raise PathSafetyError(f"Invalid {kind}: absolute paths are not allowed: {value}")
    if ":" in value:
        raise PathSafetyError(f"Invalid {kind}: drive or stream syntax is not allowed: {value}")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PathSafetyError(f"Invalid {kind}: empty, '.' or '..' segment: {value}")
    return "/".join(parts)


def rel_to_os(root: Path, rel: str) -> Path:
    return root.joinpath(*rel.split("/"))


def path_key(path: Path | str) -> str:
    """Case-normalized absolute key for comparing paths on every platform."""

    return os.path.normcase(str(Path(path).resolve()))


def same_path(left: Path | str, right: Path | str) -> bool:
    return path_key(left) == path_key(right)


def _stat_is_reparse(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def is_link_or_junction(path: Path) -> bool:
    """Return True for symbolic links and Windows junctions/reparse points."""

    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        # An unreadable component is not safe to write through either.
        return True
    if stat.S_ISLNK(st.st_mode):
        return True
    return _stat_is_reparse(st)


@dataclass(frozen=True)
class DestinationState:
    exists: bool
    is_file: bool
    is_dir: bool
    is_link: bool
    mode: Optional[int] = None
    size: Optional[int] = None
    sha256: Optional[str] = None


def inspect_destination(path: Path, with_hash: bool = False) -> DestinationState:
    """Inspect a path without following a final symlink or junction."""

    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return DestinationState(exists=False, is_file=False, is_dir=False, is_link=False)
    is_link = stat.S_ISLNK(st.st_mode) or _stat_is_reparse(st)
    if is_link:
        return DestinationState(exists=True, is_file=False, is_dir=False, is_link=True)
    is_file = stat.S_ISREG(st.st_mode)
    digest = None
    if is_file and with_hash:
        # A link could have replaced the file between lstat and open; use
        # O_NOFOLLOW where the platform supports it.
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
    return DestinationState(
        exists=True,
        is_file=is_file,
        is_dir=stat.S_ISDIR(st.st_mode),
        is_link=False,
        mode=stat.S_IMODE(st.st_mode),
        size=st.st_size if is_file else None,
        sha256=digest,
    )


def assert_safe_destination(root: Path, rel: str) -> None:
    """Reject links, junctions, non-directories in parents, and non-files at leaf."""

    root = root.resolve()
    current = root
    parts = rel.split("/")
    for index, part in enumerate(parts):
        current = current / part
        if is_link_or_junction(current):
            raise PathSafetyError(
                f"Refusing to follow a symbolic link or junction while managing "
                f"'{rel}': {current}"
            )
        if index < len(parts) - 1:
            if current.exists() and not current.is_dir():
                raise PathSafetyError(
                    f"Refusing to use '{rel}': parent is not a directory: {current}"
                )
        elif current.exists():
            try:
                st = os.lstat(current)
            except OSError as exc:
                raise PathSafetyError(f"Cannot inspect managed path '{rel}': {exc}") from exc
            if not stat.S_ISREG(st.st_mode):
                raise PathSafetyError(
                    f"Refusing to replace '{rel}': expected a regular file, found "
                    f"{'a directory' if stat.S_ISDIR(st.st_mode) else 'a special file'}: {current}"
                )
    resolved = (root / rel).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PathSafetyError(f"Managed path escapes the checkout: {rel}") from exc


def read_regular_bytes(path: Path) -> tuple[bytes, int]:
    if is_link_or_junction(path):
        raise PathSafetyError(f"Refusing to read through a link: {path}")
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode):
        raise PathSafetyError(f"Expected a regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as handle:
        return handle.read(), stat.S_IMODE(st.st_mode)


def ensure_parent_directories(root: Path, rel: str, created: Optional[List[str]] = None) -> None:
    """Create missing parent directories, recording install-created ones.

    Existing components must be real directories; links and junctions are
    rejected before anything is created.
    """

    root = root.resolve()
    parts = rel.split("/")[:-1]
    current = root
    for index, part in enumerate(parts):
        parent_rel = "/".join(parts[: index + 1])
        current = current / part
        if is_link_or_junction(current):
            raise PathSafetyError(
                f"Refusing to create a directory through a symbolic link or junction: {current}"
            )
        if current.exists():
            if not current.is_dir():
                raise PathSafetyError(
                    f"Refusing to create '{rel}': parent is not a directory: {current}"
                )
            continue
        try:
            current.mkdir()
        except FileExistsError:
            if is_link_or_junction(current) or not current.is_dir():
                raise PathSafetyError(
                    f"Unsafe directory appeared while installing: {current}"
                ) from None
        else:
            if created is not None:
                created.append(parent_rel)


def fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _make_replaceable(path: Path) -> None:
    if not path.exists():
        return
    try:
        mode = stat.S_IMODE(os.lstat(path).st_mode)
    except OSError:
        return
    if mode & stat.S_IWUSR:
        return
    try:
        os.chmod(path, mode | stat.S_IWUSR)
    except OSError:
        pass


def atomic_write_bytes(path: Path, data: bytes, mode: Optional[int]) -> None:
    """Write bytes to a sibling temporary file and atomically replace the target."""

    parent = path.parent
    if is_link_or_junction(parent):
        raise PathSafetyError(f"Refusing to write through a linked directory: {parent}")
    fd, temp_name = tempfile.mkstemp(prefix=".orca-ao-", suffix=".tmp", dir=parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temp_path, mode & 0o777)
        _make_replaceable(path)
        os.replace(temp_path, path)
        if mode is not None:
            os.chmod(path, mode & 0o777)
        fsync_directory(parent)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def remove_empty_directories(root: Path, rel_dirs: Iterable[str]) -> List[str]:
    """Remove only empty, install-created directories. Return retained ones."""

    root = root.resolve()
    retained: List[str] = []
    seen = set()
    ordered = sorted(set(rel_dirs), key=lambda item: item.count("/"), reverse=True)
    for rel in ordered:
        if rel in seen:
            continue
        seen.add(rel)
        path = rel_to_os(root, rel)
        if is_link_or_junction(path):
            retained.append(rel)
            continue
        if not path.exists():
            continue
        if not path.is_dir():
            retained.append(rel)
            continue
        try:
            os.rmdir(path)
        except OSError:
            retained.append(rel)
    return retained


def remove_regular_file(path: Path) -> bool:
    """Remove a regular file. Return True when something was removed."""

    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(st.st_mode) or _stat_is_reparse(st):
        raise PathSafetyError(f"Refusing to remove a symbolic link or junction: {path}")
    if not stat.S_ISREG(st.st_mode):
        raise PathSafetyError(f"Refusing to remove a non-file: {path}")
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    except PermissionError:
        # Windows refuses to unlink read-only files. The file is still a regular
        # non-link target that the operation owns or is restoring over.
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            os.unlink(path)
        except FileNotFoundError:
            return False
    fsync_directory(path.parent)
    return True


def mode_matches(path: Path, expected_mode: int) -> bool:
    if os.name == "nt":
        return True
    try:
        return stat.S_IMODE(os.lstat(path).st_mode) == (expected_mode & 0o777)
    except OSError:
        return False
