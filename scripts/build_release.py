#!/usr/bin/env python3
"""Build the versioned, checksummed installer ZIP published on GitHub Releases.

The archive contains only files required to install, update, verify, or
uninstall the bundle. Tests, the full Git history, local checkouts, and
development files are deliberately excluded.
"""

from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import re
import zipfile

from orca_install.bundle import load_bundle

SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
ASSET_PREFIX = "orca-advanced-orchestration"
FIXED_DATE = (1980, 1, 1, 0, 0, 0)


def _runtime_files(root: Path, bundle) -> list[Path]:
    paths = [
        "install.ps1",
        "bundle-manifest.json",
        "LICENSE",
        "scripts/manage_installation.py",
        "scripts/verify_bundle.py",
        str(bundle.manifest["patch"]["path"]),
        str(bundle.manifest["example"]["path"]),
    ]
    paths.extend(item.snapshot_path for item in bundle.files)
    paths.extend(
        path.relative_to(root).as_posix()
        for path in sorted((root / "scripts" / "orca_install").rglob("*.py"))
        if "__pycache__" not in path.parts
    )
    resolved = []
    seen = set()
    for rel in paths:
        if rel in seen:
            continue
        seen.add(rel)
        path = root.joinpath(*rel.split("/"))
        if not path.is_file():
            raise SystemExit(f"error: release file is missing: {rel}")
        resolved.append(path)
    return resolved


def build(output_dir: Path) -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[1]
    bundle = load_bundle(root)
    version = bundle.package_version
    if not SEMVER_RE.fullmatch(version):
        raise SystemExit(f"error: package.version is not semver: {version!r}")

    output_dir.mkdir(parents=True, exist_ok=True)
    name = f"{ASSET_PREFIX}-{version}.zip"
    archive_path = output_dir / name
    temp_path = output_dir / (name + ".tmp")
    files = _runtime_files(root, bundle)

    with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            rel = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(rel, date_time=FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o644 & 0xFFFF) << 16
            archive.writestr(info, path.read_bytes())
    temp_path.replace(archive_path)

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path = output_dir / (name + ".sha256")
    checksum_path.write_text(f"{digest}  {name}\n", encoding="ascii")
    return archive_path, checksum_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="dist",
        help="output directory (default: dist)",
    )
    args = parser.parse_args(argv)
    archive_path, checksum_path = build(Path(args.output))
    digest = checksum_path.read_text(encoding="ascii").split()[0]
    print(f"Release archive: {archive_path}")
    print(f"Version: {load_bundle(Path(__file__).resolve().parents[1]).package_version}")
    print(f"SHA-256: {digest}")
    print(f"Checksum file: {checksum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
