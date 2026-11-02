"""Verify the published change bundle using only the Python standard library."""

from pathlib import Path
import hashlib
import json
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "bundle-manifest.json").read_text(encoding="utf-8"))
    entries = [manifest["patch"], manifest["example"]]
    entries.extend(
        {"path": item["snapshotPath"], "sha256": item["sha256"]}
        for item in manifest["files"]
    )
    failures = []
    for entry in entries:
        path = (root / entry["path"]).resolve()
        if not path.is_relative_to(root):
            failures.append(f"Outside bundle: {entry['path']}")
            continue
        if not path.is_file():
            failures.append(f"Missing: {entry['path']}")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            failures.append(f"Hash mismatch: {entry['path']}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Verified {len(entries)} files. Orca base: {manifest['upstream']['baseCommit']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
