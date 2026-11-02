"""Verify the published change bundle using only the Python standard library."""

from pathlib import Path
import sys

from orca_install.bundle import load_bundle
from orca_install.errors import BundleError


def main():
    root = Path(__file__).resolve().parents[1]
    try:
        bundle = load_bundle(root)
    except BundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    entries = 2 + len(bundle.files)
    print(f"Verified {entries} files. Orca base: {bundle.base_commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
