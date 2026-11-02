"""Verification of the published bundle and its real 77-file patch."""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest

from helpers import REPO_ROOT, clean_git_env, run_git

from orca_install.bundle import load_bundle
from orca_install.gitutil import apply_patch

SOURCE_CHECKOUT = REPO_ROOT / "orca-source"
MANIFEST = json.loads((REPO_ROOT / "bundle-manifest.json").read_text(encoding="utf-8"))
BASE_COMMIT = MANIFEST["upstream"]["baseCommit"]


class PublishedBundleTests(unittest.TestCase):
    def test_verify_bundle_cli(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "verify_bundle.py")],
            cwd=str(REPO_ROOT),
            capture_output=True,
            env=clean_git_env(),
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        output = result.stdout.decode("utf-8", "replace")
        self.assertIn("Verified 79 files", output)
        self.assertIn(BASE_COMMIT, output)

    def test_bundle_loads_and_hashes_match(self) -> None:
        bundle = load_bundle(REPO_ROOT)
        self.assertEqual(len(bundle.files), 77)
        self.assertEqual(bundle.base_commit, BASE_COMMIT)
        self.assertEqual(len(bundle.patch_paths), 77)

    @unittest.skipUnless(SOURCE_CHECKOUT.is_dir(), "local orca-source checkout is not present")
    def test_real_patch_matches_snapshots_on_base_tree(self) -> None:
        try:
            run_git(SOURCE_CHECKOUT, "cat-file", "-e", f"{BASE_COMMIT}^{{commit}}")
        except RuntimeError:
            self.skipTest("base commit is not present in the local orca-source checkout")

        bundle = load_bundle(REPO_ROOT)
        missing_base = 0
        with tempfile.TemporaryDirectory(prefix="orca-ao-real-") as temp:
            tree = Path(temp)
            for item in bundle.files:
                result = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(SOURCE_CHECKOUT),
                        "cat-file",
                        "blob",
                        f"{BASE_COMMIT}:{item.upstream_path}",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=clean_git_env(),
                )
                if result.returncode != 0:
                    missing_base += 1
                    continue
                destination = tree.joinpath(*item.upstream_path.split("/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(result.stdout)

            patch_path = tree / ".bundle.patch"
            patch_path.write_bytes(bundle.patch_bytes)
            apply_patch(patch_path, tree)

            mismatches = []
            for item in bundle.files:
                destination = tree.joinpath(*item.upstream_path.split("/"))
                if not destination.is_file():
                    mismatches.append(f"{item.upstream_path}: missing")
                elif hashlib.sha256(destination.read_bytes()).hexdigest() != item.sha256:
                    mismatches.append(f"{item.upstream_path}: hash mismatch")
            self.assertEqual(mismatches, [])
            # 27 files are new in this bundle, so the base tree lacks them.
            self.assertEqual(missing_base, 27)


if __name__ == "__main__":
    unittest.main()
