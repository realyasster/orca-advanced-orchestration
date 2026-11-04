"""Release archive tests: contents, checksum, and offline verification."""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile

from helpers import REPO_ROOT, clean_git_env

from orca_install.bundle import load_bundle

MANIFEST = json.loads((REPO_ROOT / "bundle-manifest.json").read_text(encoding="utf-8"))
VERSION = MANIFEST["package"]["version"]


class ReleasePackageTests(unittest.TestCase):
    def build(self, output: Path) -> tuple[Path, Path]:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "build_release.py"), "--output", str(output)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=clean_git_env(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = output / f"orca-advanced-orchestration-{VERSION}.zip"
        checksum = output / f"{archive.name}.sha256"
        self.assertTrue(archive.is_file())
        self.assertTrue(checksum.is_file())
        return archive, checksum

    def test_archive_contains_only_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orca-release-") as temp:
            output = Path(temp)
            archive, checksum = self.build(output)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual(
                checksum.read_text(encoding="ascii"),
                f"{digest}  {archive.name}\n",
            )
            with zipfile.ZipFile(archive) as package:
                names = set(package.namelist())
                self.assertIn("install.ps1", names)
                self.assertIn("bundle-manifest.json", names)
                self.assertIn("LICENSE", names)
                self.assertIn("scripts/manage_installation.py", names)
                self.assertIn("scripts/orca_install/updater.py", names)
                self.assertIn("scripts/verify_bundle.py", names)
                self.assertIn(MANIFEST["patch"]["path"], names)
                self.assertIn(MANIFEST["example"]["path"], names)
                for entry in MANIFEST["files"]:
                    self.assertIn(entry["snapshotPath"], names)
                expected_modules = {
                    path.relative_to(REPO_ROOT).as_posix()
                    for path in (REPO_ROOT / "scripts" / "orca_install").rglob("*.py")
                    if "__pycache__" not in path.parts
                }
                self.assertTrue(expected_modules <= names, expected_modules - names)
                forbidden = ("tests/", "orca-source/", "docs/", ".git/", "README")
                for name in names:
                    self.assertFalse(
                        name.startswith(forbidden), f"unexpected development file: {name}"
                    )
                self.assertNotIn(".github/workflows/release.yml", names)
                package.extractall(output / "extracted")
            extracted = output / "extracted"
            bundle = load_bundle(extracted)
            self.assertEqual(bundle.package_version, VERSION)
            self.assertEqual(len(bundle.files), len(MANIFEST["files"]))
            verify = subprocess.run(
                [sys.executable, str(extracted / "scripts" / "verify_bundle.py")],
                cwd=str(extracted),
                capture_output=True,
                text=True,
                env=clean_git_env(),
            )
            self.assertEqual(verify.returncode, 0, verify.stderr)
            self.assertIn(f"Verified {2 + len(bundle.files)} files", verify.stdout)
            imports = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.path.insert(0, 'scripts'); "
                    "import orca_install.cli, orca_install.updater; "
                    "print('IMPORT OK')",
                ],
                cwd=str(extracted),
                capture_output=True,
                text=True,
                env=clean_git_env(),
            )
            self.assertEqual(imports.returncode, 0, imports.stderr)
            self.assertIn("IMPORT OK", imports.stdout)

    def test_archive_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orca-release-a-") as first, tempfile.TemporaryDirectory(
            prefix="orca-release-b-"
        ) as second:
            archive_a, _ = self.build(Path(first))
            archive_b, _ = self.build(Path(second))
            self.assertEqual(archive_a.read_bytes(), archive_b.read_bytes())


if __name__ == "__main__":
    unittest.main()
