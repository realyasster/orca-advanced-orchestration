"""Load and verify the published change bundle using only the standard library."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence
import hashlib
import json
import re
import shlex

from .errors import BundleError, PathSafetyError
from .paths import normalize_relative_path, sha256_bytes

MANIFEST_NAME = "bundle-manifest.json"
BUNDLE_FORMAT_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _relative(value: object, label: str) -> str:
    try:
        return normalize_relative_path(value, label)
    except PathSafetyError as exc:
        raise BundleError(str(exc)) from exc


@dataclass(frozen=True)
class BundleFile:
    upstream_path: str
    snapshot_path: str
    sha256: str


@dataclass(frozen=True)
class BundlePack:
    id: str
    label: str
    description: str
    files: Sequence[str]
    requires: Sequence[str] = ()


@dataclass(frozen=True)
class Bundle:
    root: Path
    manifest: Dict
    patch_bytes: bytes
    example_bytes: bytes
    files: Sequence[BundleFile]
    packs: Sequence[BundlePack]
    base_commit: str
    implementation_commit: Optional[str]
    fingerprint: str

    @property
    def patch_paths(self) -> List[str]:
        return [item.upstream_path for item in self.files]

    @property
    def pack_ids(self) -> List[str]:
        return [pack.id for pack in self.packs]

    def resolve_pack_ids(self, requested: Optional[Sequence[str]]) -> List[str]:
        """Return manifest-ordered pack ids; no packs/selection means the whole bundle."""
        if not self.packs:
            if requested:
                raise BundleError("This bundle does not define selectable packs")
            return []
        if not requested:
            return self.pack_ids
        wanted = {value.strip() for value in requested if value.strip()}
        unknown = sorted(wanted - set(self.pack_ids))
        if unknown:
            raise BundleError("Unknown pack(s): " + ", ".join(unknown))
        if not wanted:
            raise BundleError("Select at least one pack")
        # Pull in declared dependencies; the loader has already rejected cycles.
        changed = True
        while changed:
            changed = False
            for pack in self.packs:
                if pack.id in wanted and not set(pack.requires).issubset(wanted):
                    wanted.update(pack.requires)
                    changed = True
        return [pack_id for pack_id in self.pack_ids if pack_id in wanted]

    def paths_for_packs(self, pack_ids: Sequence[str]) -> List[str]:
        if not self.packs:
            return self.patch_paths
        selected = set(pack_ids)
        paths = {
            path
            for pack in self.packs
            if pack.id in selected
            for path in pack.files
        }
        return [item.upstream_path for item in self.files if item.upstream_path in paths]

    def resolve_selected_paths(self, selected: Optional[Sequence[str]]) -> List[str]:
        """Normalize a caller selection: None means all, [] is invalid, unknown paths fail."""
        if selected is None:
            return self.patch_paths
        paths = list(dict.fromkeys(selected))
        if not paths:
            raise BundleError("Selected file set must not be empty")
        unknown = sorted(set(paths) - set(self.patch_paths))
        if unknown:
            raise BundleError("Selected file is not in the bundle: " + ", ".join(unknown[:5]))
        wanted = set(paths)
        return [path for path in self.patch_paths if path in wanted]

    def patch_bytes_for_paths(self, paths: Sequence[str]) -> bytes:
        selected = set(paths)
        if selected == set(self.patch_paths):
            return self.patch_bytes
        return filter_patch_paths(self.patch_bytes, selected)


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BundleError(f"Bundle manifest field '{label}' must be a non-empty string")
    return value


def _require_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value.lower()):
        raise BundleError(f"Bundle manifest field '{label}' must be a SHA-256 hex digest")
    return value.lower()


def _resolve_bundle_path(root: Path, value: object, label: str) -> Path:
    rel = _relative(value, label)
    path = root.joinpath(*rel.split("/")).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise BundleError(f"Bundle path escapes the bundle directory: {value}") from exc
    if not path.is_file():
        raise BundleError(f"Bundle file is missing: {value}")
    return path


def _read_and_hash(path: Path, label: str) -> tuple[bytes, str]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise BundleError(f"Could not read bundle file '{label}': {exc}") from exc
    return data, sha256_bytes(data)


def _split_git_header(rest: str) -> tuple[str, str]:
    """Split the right-hand side of a ``diff --git`` header."""

    if rest.startswith('"'):
        try:
            parts = shlex.split(rest)
        except ValueError as exc:
            raise BundleError(f"Unsupported quoted path in patch header: {rest}") from exc
        if len(parts) != 2:
            raise BundleError(f"Malformed diff header: {rest}")
        return parts[0], parts[1]
    left, marker, right = rest.rpartition(" b/")
    if not marker:
        raise BundleError(f"Malformed diff header: {rest}")
    if not left.startswith("a/"):
        raise BundleError(f"Malformed diff header (expected a/ prefix): {rest}")
    return left[2:], right


def _patch_header_paths(header: bytes) -> tuple[Optional[str], Optional[str]]:
    rest = header[len(b"diff --git ") :].rstrip(b"\r\n")
    if rest.startswith(b'"'):
        try:
            old, new = _split_git_header(rest.decode("utf-8", "surrogateescape"))
        except BundleError:
            return None, None
        return old, new
    left, marker, right = rest.rpartition(b" b/")
    if not marker or not left.startswith(b"a/"):
        return None, None
    return (
        left[2:].decode("utf-8", "surrogateescape"),
        right.decode("utf-8", "surrogateescape"),
    )


def filter_patch_paths(patch_bytes: bytes, paths: Sequence[str]) -> bytes:
    """Keep complete file diffs byte-for-byte for the selected old or new paths."""
    selected = set(paths)
    blocks: List[tuple[set[str], List[bytes]]] = []
    current: List[bytes] = []
    current_paths: set[str] = set()
    for part in patch_bytes.split(b"\n"):
        if part.startswith(b"diff --git "):
            if current:
                blocks.append((current_paths, current))
            old, new = _patch_header_paths(part)
            current = [part]
            current_paths = {path for path in (old, new) if path}
            continue
        if current:
            current.append(part)
    if current:
        blocks.append((current_paths, current))
    kept = [
        b"\n".join(block)
        for block_paths, block in blocks
        if block_paths & selected
    ]
    result = b"\n".join(kept)
    # A selected block that is not last originally lost only its separator; restore it
    # without rewriting the block bytes (CRLF, blank lines, and "\\ No newline" survive).
    if result and patch_bytes.endswith(b"\n") and not result.endswith(b"\n"):
        result += b"\n"
    return result


def patch_affected_paths(patch_bytes: bytes) -> List[str]:
    """Extract the affected paths from a unified Git patch.

    Only modifications and additions are supported; renames and deletions
    would make a backup/restore record ambiguous, so they are rejected.
    """

    text = patch_bytes.decode("utf-8", "replace")
    paths: List[str] = []
    for line in text.splitlines():
        if line.startswith("old mode ") or line.startswith("new mode "):
            raise BundleError(
                "Bundle patch must not change file modes on existing files; "
                "mode-only changes are ambiguous for a source checkout"
            )
        if line.startswith("deleted file mode "):
            raise BundleError(
                "Bundle patch must not delete files; deletions cannot be represented "
                "in the managed backup/restore record"
            )
        if (
            line.startswith("rename from ")
            or line.startswith("rename to ")
            or line.startswith("similarity index ")
        ):
            raise BundleError(
                "Bundle patch must not rename or copy files; renames are ambiguous "
                "for a source checkout"
            )
        if not line.startswith("diff --git "):
            continue
        old, new = _split_git_header(line[len("diff --git ") :])
        if old != new:
            raise BundleError(f"Bundle patch must not rename files: {old} -> {new}")
        paths.append(_relative(old, "patch path"))
    if not paths:
        raise BundleError("Bundle patch contains no file changes")
    if len(paths) != len(set(paths)):
        raise BundleError("Bundle patch lists the same file more than once")
    return paths


def _assert_pack_dependencies_acyclic(packs: Sequence[BundlePack]) -> None:
    by_id = {pack.id: pack for pack in packs}
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(pack_id: str, chain: List[str]) -> None:
        if pack_id in done:
            return
        if pack_id in visiting:
            cycle = " -> ".join([*chain, pack_id])
            raise BundleError(f"Bundle pack dependency cycle: {cycle}")
        visiting.add(pack_id)
        for required in by_id[pack_id].requires:
            visit(required, [*chain, pack_id])
        visiting.remove(pack_id)
        done.add(pack_id)

    for pack in packs:
        visit(pack.id, [])


def _fingerprint(manifest: Dict, files: Sequence[BundleFile]) -> str:
    payload = {
        "formatVersion": BUNDLE_FORMAT_VERSION,
        "baseCommit": manifest["upstream"]["baseCommit"],
        "repository": manifest["upstream"].get("repository"),
        "version": manifest["upstream"].get("version"),
        "implementationCommit": manifest.get("implementationCommit"),
        "patchSha256": manifest["patch"]["sha256"],
        "exampleSha256": manifest["example"]["sha256"],
        "files": [{"path": item.upstream_path, "sha256": item.sha256} for item in files],
    }
    # Old bundles without packs must keep their historical fingerprint.
    if manifest.get("packs"):
        payload["packs"] = [
            {
                "id": entry["id"],
                "files": list(entry["files"]),
                "requires": list(entry.get("requires", [])),
            }
            for entry in manifest["packs"]
        ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_bundle(bundle_root: Path | str) -> Bundle:
    """Load, validate, and fully verify a change bundle.

    Every byte used later is read exactly once here. The returned patch bytes
    are the verified bytes, which prevents a later on-disk change from slipping
    between verification and installation.
    """

    root = Path(bundle_root).expanduser().resolve()
    if not root.is_dir():
        raise BundleError(f"Bundle directory does not exist: {root}")
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise BundleError(f"Bundle manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"Could not parse bundle manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise BundleError("Bundle manifest must be a JSON object")
    if manifest.get("formatVersion") != BUNDLE_FORMAT_VERSION:
        raise BundleError(
            f"Unsupported bundle manifest formatVersion: {manifest.get('formatVersion')!r} "
            f"(expected {BUNDLE_FORMAT_VERSION})"
        )

    upstream = manifest.get("upstream")
    if not isinstance(upstream, dict):
        raise BundleError("Bundle manifest field 'upstream' must be an object")
    base_commit = _require_string(upstream.get("baseCommit"), "upstream.baseCommit").lower()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", base_commit):
        raise BundleError("Bundle manifest upstream.baseCommit is not a Git object id")
    _require_string(upstream.get("repository"), "upstream.repository")
    _require_string(upstream.get("version"), "upstream.version")

    implementation_commit = manifest.get("implementationCommit")
    if implementation_commit is not None:
        implementation_commit = _require_string(
            implementation_commit, "implementationCommit"
        ).lower()

    patch_info = manifest.get("patch")
    if not isinstance(patch_info, dict):
        raise BundleError("Bundle manifest field 'patch' must be an object")
    patch_rel = _relative(patch_info.get("path"), "patch.path")
    patch_sha = _require_hash(patch_info.get("sha256"), "patch.sha256")
    patch_file = _resolve_bundle_path(root, patch_rel, "patch.path")
    patch_bytes, actual_patch_sha = _read_and_hash(patch_file, patch_rel)
    if actual_patch_sha != patch_sha:
        raise BundleError(
            f"Patch hash mismatch for '{patch_rel}': expected {patch_sha}, got {actual_patch_sha}"
        )

    example_info = manifest.get("example")
    if not isinstance(example_info, dict):
        raise BundleError("Bundle manifest field 'example' must be an object")
    example_rel = _relative(example_info.get("path"), "example.path")
    example_sha = _require_hash(example_info.get("sha256"), "example.sha256")
    example_file = _resolve_bundle_path(root, example_rel, "example.path")
    example_bytes, actual_example_sha = _read_and_hash(example_file, example_rel)
    if actual_example_sha != example_sha:
        raise BundleError(
            f"Example hash mismatch for '{example_rel}': expected {example_sha}, "
            f"got {actual_example_sha}"
        )

    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise BundleError("Bundle manifest field 'files' must be a non-empty array")
    files: List[BundleFile] = []
    seen = set()
    seen_casefold = set()
    for index, entry in enumerate(raw_files):
        if not isinstance(entry, dict):
            raise BundleError(f"Bundle manifest files[{index}] must be an object")
        upstream_path = _relative(
            entry.get("upstreamPath"), f"files[{index}].upstreamPath"
        )
        snapshot_path = _relative(
            entry.get("snapshotPath"), f"files[{index}].snapshotPath"
        )
        expected = _require_hash(entry.get("sha256"), f"files[{index}].sha256")
        if upstream_path in seen:
            raise BundleError(f"Duplicate managed path in bundle: {upstream_path}")
        folded = upstream_path.casefold()
        if folded in seen_casefold:
            raise BundleError(
                f"Managed paths differ only by case, which is unsafe on Windows: {upstream_path}"
            )
        seen.add(upstream_path)
        seen_casefold.add(folded)
        snapshot_file = _resolve_bundle_path(root, snapshot_path, f"files[{index}].snapshotPath")
        _, actual = _read_and_hash(snapshot_file, snapshot_path)
        if actual != expected:
            raise BundleError(
                f"Snapshot hash mismatch for '{snapshot_path}': expected {expected}, got {actual}"
            )
        files.append(
            BundleFile(upstream_path=upstream_path, snapshot_path=snapshot_path, sha256=expected)
        )

    manifest_paths = [item.upstream_path for item in files]
    raw_packs = manifest.get("packs")
    packs: List[BundlePack] = []
    if raw_packs is not None:
        if not isinstance(raw_packs, list) or not raw_packs:
            raise BundleError("Bundle manifest field 'packs' must be a non-empty array")
        packed_paths = set()
        pack_ids = set()
        for index, entry in enumerate(raw_packs):
            if not isinstance(entry, dict):
                raise BundleError(f"Bundle manifest packs[{index}] must be an object")
            pack_id = _require_string(entry.get("id"), f"packs[{index}].id")
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", pack_id):
                raise BundleError(f"Bundle pack id is invalid: {pack_id!r}")
            if pack_id in pack_ids:
                raise BundleError(f"Duplicate pack id in bundle: {pack_id}")
            pack_ids.add(pack_id)
            raw_files = entry.get("files")
            if not isinstance(raw_files, list) or not raw_files:
                raise BundleError(f"Bundle pack '{pack_id}' must list at least one file")
            pack_files: List[str] = []
            for raw_path in raw_files:
                rel = _relative(raw_path, f"packs[{index}].files")
                if rel not in manifest_paths:
                    raise BundleError(
                        f"Pack '{pack_id}' names a file that is not in the bundle: {rel}"
                    )
                if rel in packed_paths:
                    raise BundleError(f"Bundle file is assigned to more than one pack: {rel}")
                packed_paths.add(rel)
                pack_files.append(rel)
            raw_requires = entry.get("requires", [])
            if not isinstance(raw_requires, list) or not all(
                isinstance(item, str) and item for item in raw_requires
            ):
                raise BundleError(f"Bundle pack '{pack_id}' requires must be a string array")
            if len(set(raw_requires)) != len(raw_requires):
                raise BundleError(f"Bundle pack '{pack_id}' lists a dependency twice")
            if pack_id in raw_requires:
                raise BundleError(f"Bundle pack '{pack_id}' cannot require itself")
            packs.append(
                BundlePack(
                    id=pack_id,
                    label=_require_string(entry.get("label"), f"packs[{index}].label"),
                    description=_require_string(
                        entry.get("description"), f"packs[{index}].description"
                    ),
                    files=tuple(pack_files),
                    requires=tuple(raw_requires),
                )
            )
        if packed_paths != set(manifest_paths):
            missing = sorted(set(manifest_paths) - packed_paths)
            raise BundleError(
                "Bundle packs must cover every managed file"
                + (": " + ", ".join(missing[:5]) if missing else "")
            )
        for pack in packs:
            unknown_requires = sorted(set(pack.requires) - pack_ids)
            if unknown_requires:
                raise BundleError(
                    f"Pack '{pack.id}' requires unknown pack(s): "
                    + ", ".join(unknown_requires)
                )
        _assert_pack_dependencies_acyclic(packs)

    patch_paths = patch_affected_paths(patch_bytes)
    missing_from_patch = sorted(set(manifest_paths) - set(patch_paths))
    extra_in_patch = sorted(set(patch_paths) - set(manifest_paths))
    if missing_from_patch or extra_in_patch:
        details = []
        if missing_from_patch:
            details.append("not in patch: " + ", ".join(missing_from_patch[:5]))
        if extra_in_patch:
            details.append("not in manifest: " + ", ".join(extra_in_patch[:5]))
        raise BundleError("Bundle patch and file list disagree (" + "; ".join(details) + ")")

    fingerprint = _fingerprint(manifest, files)
    return Bundle(
        root=root,
        manifest=manifest,
        patch_bytes=patch_bytes,
        example_bytes=example_bytes,
        files=tuple(files),
        packs=tuple(packs),
        base_commit=base_commit,
        implementation_commit=implementation_commit,
        fingerprint=fingerprint,
    )
