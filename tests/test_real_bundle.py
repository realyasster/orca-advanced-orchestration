"""Verification of the published bundle and its real source patch."""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import REPO_ROOT, clean_git_env, run_git

from orca_install.bundle import load_bundle
from orca_install.errors import BundleError
from orca_install.gitutil import apply_patch

SOURCE_CHECKOUT = Path(
    os.environ.get("ORCA_SOURCE_CHECKOUT", REPO_ROOT / "orca-source")
)
MANIFEST = json.loads((REPO_ROOT / "bundle-manifest.json").read_text(encoding="utf-8"))
BASE_COMMIT = MANIFEST["upstream"]["baseCommit"]
BUNDLE_FILES = len(MANIFEST["files"])
VERIFIED_FILES = BUNDLE_FILES + 2


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
        self.assertIn(f"Verified {VERIFIED_FILES} files", output)
        self.assertIn(BASE_COMMIT, output)

    def test_bundle_loads_and_hashes_match(self) -> None:
        bundle = load_bundle(REPO_ROOT)
        self.assertEqual(len(bundle.files), BUNDLE_FILES)
        self.assertEqual(bundle.base_commit, BASE_COMMIT)
        self.assertEqual(len(bundle.patch_paths), BUNDLE_FILES)

    def test_packs_cover_every_file_once(self) -> None:
        bundle = load_bundle(REPO_ROOT)
        self.assertEqual(bundle.pack_ids, ["orchestration", "todo"])
        counts = {pack.id: len(pack.files) for pack in bundle.packs}
        self.assertGreater(counts["orchestration"], 0)
        self.assertGreater(counts["todo"], 0)
        self.assertEqual(
            len(bundle.paths_for_packs(["orchestration"])), counts["orchestration"]
        )
        self.assertEqual(len(bundle.paths_for_packs(["todo"])), counts["todo"])
        self.assertEqual(
            len(bundle.paths_for_packs(["orchestration", "todo"])), BUNDLE_FILES
        )
        with self.assertRaises(BundleError):
            bundle.resolve_pack_ids(["missing"])

    def test_usage_docs_counts_match_manifest(self) -> None:
        for readme in ("docs/USAGE.md", "docs/USAGE.en.md"):
            text = (REPO_ROOT / readme).read_text(encoding="utf-8")
            self.assertIn(str(BUNDLE_FILES), text, readme)
            self.assertIn(str(VERIFIED_FILES), text, readme)

    @unittest.skipUnless(SOURCE_CHECKOUT.is_dir(), "local orca-source checkout is not present")
    def test_each_pack_patch_applies_independently(self) -> None:
        try:
            run_git(SOURCE_CHECKOUT, "cat-file", "-e", f"{BASE_COMMIT}^{{commit}}")
        except RuntimeError:
            self.skipTest("base commit is not present in the local orca-source checkout")

        bundle = load_bundle(REPO_ROOT)
        for pack in bundle.packs:
            with self.subTest(pack=pack.id), tempfile.TemporaryDirectory(
                prefix=f"orca-ao-pack-{pack.id}-"
            ) as temp:
                tree = Path(temp)
                for rel in pack.files:
                    result = subprocess.run(
                        [
                            "git",
                            "-C",
                            str(SOURCE_CHECKOUT),
                            "cat-file",
                            "blob",
                            f"{BASE_COMMIT}:{rel}",
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        env=clean_git_env(),
                    )
                    if result.returncode != 0:
                        continue
                    destination = tree.joinpath(*rel.split("/"))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(result.stdout)

                patch_path = tree / f".{pack.id}.patch"
                patch_path.write_bytes(bundle.patch_bytes_for_paths(pack.files))
                apply_patch(patch_path, tree)

                mismatches = []
                for rel in pack.files:
                    expected = next(item for item in bundle.files if item.upstream_path == rel)
                    destination = tree.joinpath(*rel.split("/"))
                    if not destination.is_file():
                        mismatches.append(f"{rel}: missing")
                    elif hashlib.sha256(destination.read_bytes()).hexdigest() != expected.sha256:
                        mismatches.append(f"{rel}: hash mismatch")
                self.assertEqual(mismatches, [], pack.id)

    @unittest.skipUnless(SOURCE_CHECKOUT.is_dir(), "local orca-source checkout is not present")
    def test_real_patch_matches_snapshots_on_base_tree(self) -> None:
        try:
            run_git(SOURCE_CHECKOUT, "cat-file", "-e", f"{BASE_COMMIT}^{{commit}}")
        except RuntimeError:
            self.skipTest("base commit is not present in the local orca-source checkout")

        bundle = load_bundle(REPO_ROOT)
        base_paths = set(
            run_git(SOURCE_CHECKOUT, "ls-tree", "-r", "--name-only", BASE_COMMIT)
            .decode("utf-8", "replace")
            .splitlines()
        )
        expected_new = sum(1 for item in bundle.files if item.upstream_path not in base_paths)
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
            self.assertEqual(missing_base, expected_new)


if __name__ == "__main__":
    unittest.main()
