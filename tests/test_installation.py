"""End-to-end tests for the backup-aware installer using temporary Git repos."""

from __future__ import annotations

from pathlib import Path
from unittest import mock
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

from helpers import (
    REPO_ROOT,
    build_fixture,
    clean_git_env,
    read_manifest,
    run_git,
    sha,
    snapshot_tree,
    snapshot_worktree,
    write_manifest,
)

from orca_install import cli, installer, uninstaller
from orca_install.bundle import patch_affected_paths
from orca_install.errors import (
    BundleError,
    InstallationError,
    InterruptedOperationError,
    LockError,
    PathSafetyError,
    RecoveryRequiredError,
    StateError,
)
from orca_install.lock import InstallationLock
from orca_install.status import collect_status


class InstallationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="orca-ao-test-")
        self.root = Path(self.temp.name)
        self.fx = build_fixture(self.root)
        self.source = self.fx.source
        self.bundle = self.fx.bundle

    def tearDown(self) -> None:
        self.temp.cleanup()

    def install(self, dry_run: bool = False):
        return installer.install(self.bundle, self.source, dry_run=dry_run)

    def uninstall(self, dry_run: bool = False):
        return uninstaller.uninstall(self.source, dry_run=dry_run)

    def status(self):
        return collect_status(self.source)

    def backup_digest(self) -> dict:
        state = self.fx.load_state()
        return snapshot_tree(Path(state["installation"]["backup"]["path"]), include_git=False)

    def install_ok(self):
        result = self.install()
        self.assertEqual(result.outcome, "installed")
        return result

    # ------------------------------------------------------------------
    # Happy path and exact restoration
    # ------------------------------------------------------------------
    def test_roundtrip_restores_exact_original_bytes(self) -> None:
        before = snapshot_worktree(self.source)
        result = self.install_ok()
        self.assertEqual(result.updated, 5)
        self.assertEqual(result.added, 2)
        self.assertEqual(self.fx.read("src/app.ts"), installer_patched_app())
        self.assertTrue(self.fx.path("src/new.ts").is_file())
        self.assertTrue(self.fx.path("newdir/created/file.txt").is_file())

        report = self.status()
        self.assertEqual(report.outcome, "installed")
        self.assertTrue(report.comparison.clean)

        result = self.uninstall()
        self.assertEqual(result.outcome, "uninstalled")
        self.assertEqual(result.restored, 5)
        self.assertEqual(result.removed, 2)
        self.assertEqual(snapshot_worktree(self.source), before)
        self.fx.assert_worktree_matches_base(self)
        self.assertEqual(self.status().outcome, "uninstalled")

    def test_new_directories_are_removed_only_when_empty(self) -> None:
        self.install_ok()
        self.assertTrue(self.fx.path("newdir/created").is_dir())
        self.uninstall()
        self.assertFalse(self.fx.path("newdir").exists())

    def test_unrelated_files_and_git_state_are_preserved(self) -> None:
        untracked = self.fx.path("notes/local.txt")
        untracked.parent.mkdir()
        untracked.write_bytes(b"my notes\n")
        head = run_git(self.source, "rev-parse", "HEAD")
        index = run_git(self.source, "diff", "--cached", "--name-only")

        self.install_ok()
        self.assertEqual(self.fx.read("unrelated/keep.txt"), b"keep me\n")
        self.assertEqual(untracked.read_bytes(), b"my notes\n")
        self.uninstall()

        self.assertEqual(untracked.read_bytes(), b"my notes\n")
        self.assertEqual(run_git(self.source, "rev-parse", "HEAD"), head)
        self.assertEqual(run_git(self.source, "diff", "--cached", "--name-only"), index)
        self.assertEqual(self.fx.read("unrelated/keep.txt"), b"keep me\n")

    def test_status_and_dry_runs_are_read_only(self) -> None:
        before = snapshot_tree(self.source)
        report = self.status()
        self.assertEqual(report.outcome, "not installed")
        self.assertFalse(self.fx.data_dir().exists())

        result = self.install(dry_run=True)
        self.assertEqual(result.outcome, "dry-run")
        self.assertFalse(self.fx.data_dir().exists())
        self.assertEqual(snapshot_tree(self.source), before)

        self.install_ok()
        installed = snapshot_tree(self.source)
        self.status()
        dry = self.uninstall(dry_run=True)
        self.assertEqual(dry.outcome, "dry-run")
        self.assertEqual(dry.restored, 5)
        self.assertEqual(dry.removed, 2)
        self.assertEqual(snapshot_tree(self.source), installed)

    def test_idempotent_install_does_not_overwrite_backup(self) -> None:
        first = self.install_ok()
        backup = Path(first.backup_path)
        digest = self.backup_digest()
        state_before = self.fx.state_path().read_bytes()

        second = self.install()
        self.assertEqual(second.outcome, "already-installed")
        self.assertEqual(second.installation_id, first.installation_id)
        self.assertEqual(self.backup_digest(), digest)
        self.assertEqual(self.fx.state_path().read_bytes(), state_before)

        self.fx.write("src/app.ts", b"user edit after install\n")
        third = self.install()
        self.assertEqual(third.outcome, "already-installed")
        self.assertIn("src/app.ts", third.modified_since_install)
        self.assertEqual(self.fx.read("src/app.ts"), b"user edit after install\n")
        self.assertTrue(backup.is_dir())

    def test_crlf_bytes_and_permissions_are_restored(self) -> None:
        # 0o555 exercises a read-only target on Windows as well as the
        # executable bit on POSIX.
        os.chmod(self.fx.path("tools/run.sh"), 0o555)
        self.fx.base_modes["tools/run.sh"] = 0o555
        self.install_ok()
        installed = self.fx.read("crlf.txt")
        self.assertEqual(installed, b"one\r\ntwo changed\r\nthree\r\n")
        self.assertNotIn(b"\n", installed.replace(b"\r\n", b""))
        if os.name != "nt":
            self.assertEqual(
                stat.S_IMODE(os.stat(self.fx.path("tools/run.sh")).st_mode), 0o555
            )
        self.uninstall()
        self.assertEqual(self.fx.read("crlf.txt"), b"one\r\ntwo\r\nthree\r\n")
        if os.name != "nt":
            self.assertEqual(
                stat.S_IMODE(os.stat(self.fx.path("tools/run.sh")).st_mode),
                self.fx.base_modes["tools/run.sh"],
            )

    def test_compatible_local_edits_are_preserved(self) -> None:
        local_docs = self.fx.read("docs/readme.md").replace(b"tail d", b"local tail d")
        self.fx.write("docs/readme.md", local_docs)
        result = self.install_ok()
        self.assertIn("docs/readme.md", result.preserved_edits)
        installed = self.fx.read("docs/readme.md")
        self.assertIn(b"new body two", installed)
        self.assertIn(b"local tail d", installed)
        self.uninstall()
        self.assertEqual(self.fx.read("docs/readme.md"), local_docs)

    def test_conflicting_patch_changes_nothing(self) -> None:
        self.fx.write("src/app.ts", self.fx.read("src/app.ts").replace(b"line 10", b"user line 10"))
        before = snapshot_worktree(self.source)
        with self.assertRaises(InstallationError) as context:
            self.install()
        self.assertIn("patch", str(context.exception).lower())
        self.assertEqual(snapshot_worktree(self.source), before)
        self.assertFalse(self.fx.state_path().exists())

    def test_wrong_head_commit_is_rejected(self) -> None:
        self.fx.write("unrelated/another.txt", b"another\n")
        run_git(self.source, "add", "unrelated/another.txt")
        run_git(self.source, "commit", "-qm", "another commit")
        before = snapshot_worktree(self.source)
        with self.assertRaises(InstallationError) as context:
            self.install()
        self.assertIn("HEAD", str(context.exception))
        self.assertEqual(snapshot_worktree(self.source), before)
        self.assertFalse(self.fx.state_path().exists())

    def test_source_must_be_a_git_checkout(self) -> None:
        plain = self.root / "plain-directory"
        plain.mkdir()
        with self.assertRaises(InstallationError) as context:
            installer.install(self.bundle, plain)
        self.assertIn("Git", str(context.exception))

    def test_different_package_cannot_replace_the_first_backup(self) -> None:
        first = self.install_ok()
        digest = self.backup_digest()
        manifest = read_manifest(self.bundle)
        manifest["upstream"]["version"] = "another-version"
        write_manifest(self.bundle, manifest)

        before = snapshot_worktree(self.source)
        with self.assertRaises(InstallationError) as context:
            self.install()
        self.assertIn("different package", str(context.exception))
        self.assertEqual(snapshot_worktree(self.source), before)
        self.assertEqual(self.fx.load_state()["installation"]["installationId"], first.installation_id)
        self.assertEqual(self.backup_digest(), digest)

    # ------------------------------------------------------------------
    # Uninstall: archives and safety
    # ------------------------------------------------------------------
    def test_changed_and_deleted_files_are_archived_before_restore(self) -> None:
        self.install_ok()
        self.fx.write("src/app.ts", b"edited original after install\n")
        self.fx.write("src/new.ts", b"edited new file after install\n")
        self.fx.path("src/deep/nested/file.ts").unlink()

        result = self.uninstall()
        self.assertEqual(result.outcome, "uninstalled")
        self.assertEqual(result.archived, 3)
        self.assertIsNotNone(result.recovery_archive)
        archive = Path(result.recovery_archive)
        manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
        entries = {entry["path"]: entry for entry in manifest["entries"]}
        self.assertEqual(entries["src/app.ts"]["reason"], "modified-after-install")
        self.assertEqual(entries["src/new.ts"]["reason"], "modified-after-install")
        self.assertEqual(entries["src/deep/nested/file.ts"]["reason"], "missing-before-uninstall")
        self.assertIsNone(entries["src/deep/nested/file.ts"]["archivedFile"])
        self.assertEqual(
            (archive / entries["src/app.ts"]["archivedFile"]).read_bytes(),
            b"edited original after install\n",
        )
        self.assertEqual(
            (archive / entries["src/new.ts"]["archivedFile"]).read_bytes(),
            b"edited new file after install\n",
        )
        self.fx.assert_worktree_matches_base(self)
        self.assertFalse(self.fx.path("src/new.ts").exists())

    def test_unexpected_directory_at_managed_path_is_not_deleted(self) -> None:
        self.install_ok()
        target = self.fx.path("src/new.ts")
        target.unlink()
        target.mkdir()
        (target / "user.txt").write_bytes(b"user data\n")
        before = snapshot_worktree(self.source)
        with self.assertRaises(InstallationError) as context:
            self.uninstall()
        self.assertIn("Unexpected", str(context.exception))
        self.assertEqual(snapshot_worktree(self.source), before)
        self.assertEqual((target / "user.txt").read_bytes(), b"user data\n")
        self.assertEqual(self.fx.load_state()["installation"]["status"], "installed")

    def test_user_content_in_created_directory_is_kept(self) -> None:
        self.install_ok()
        user_file = self.fx.path("newdir/created/user.txt")
        user_file.write_bytes(b"mine\n")
        result = self.uninstall()
        self.assertTrue(user_file.is_file())
        self.assertTrue(self.fx.path("newdir/created").is_dir())
        self.assertIn("newdir/created", result.retained_directories)

    def test_second_uninstall_is_a_safe_noop(self) -> None:
        self.install_ok()
        self.uninstall()
        state_before = self.fx.state_path().read_bytes()
        result = self.uninstall()
        self.assertEqual(result.outcome, "not-installed")
        self.assertEqual(self.fx.state_path().read_bytes(), state_before)

    def test_uninstall_does_not_need_the_bundle(self) -> None:
        self.install_ok()
        shutil.rmtree(self.bundle)
        result = self.uninstall()
        self.assertEqual(result.outcome, "uninstalled")
        self.fx.assert_worktree_matches_base(self)

    # ------------------------------------------------------------------
    # Backup and state validation
    # ------------------------------------------------------------------
    def test_missing_backup_file_blocks_uninstall(self) -> None:
        self.install_ok()
        state = self.fx.load_state()
        backup_manifest = json.loads(
            Path(state["installation"]["backup"]["manifestPath"]).read_text(encoding="utf-8")
        )
        entry = next(item for item in backup_manifest["files"] if item["existed"])
        backup_file = Path(state["installation"]["backup"]["path"]) / "files" / entry["path"]
        backup_file.unlink()
        before = snapshot_worktree(self.source)
        with self.assertRaises(InstallationError):
            self.uninstall()
        self.assertEqual(snapshot_worktree(self.source), before)
        self.assertEqual(self.fx.load_state()["installation"]["status"], "installed")

    def test_corrupt_backup_file_blocks_uninstall(self) -> None:
        self.install_ok()
        state = self.fx.load_state()
        backup_manifest = json.loads(
            Path(state["installation"]["backup"]["manifestPath"]).read_text(encoding="utf-8")
        )
        entry = next(item for item in backup_manifest["files"] if item["existed"])
        backup_file = Path(state["installation"]["backup"]["path"]) / "files" / entry["path"]
        backup_file.write_bytes(b"corrupted\n")
        before = snapshot_worktree(self.source)
        with self.assertRaises(InstallationError):
            self.uninstall()
        self.assertEqual(snapshot_worktree(self.source), before)

    def test_invalid_state_is_rejected(self) -> None:
        self.fx.data_dir().mkdir(parents=True, exist_ok=True)
        self.fx.state_path().write_text("{not json", encoding="utf-8")
        before = snapshot_worktree(self.source)
        with self.assertRaises(StateError):
            self.uninstall()
        self.assertEqual(snapshot_worktree(self.source), before)

    def test_state_path_traversal_is_rejected(self) -> None:
        self.install_ok()
        state = self.fx.load_state()
        state["installation"]["managedFiles"][0]["path"] = "../escape.txt"
        self.fx.save_state(state)
        before = snapshot_worktree(self.source)
        with self.assertRaises(StateError):
            self.uninstall()
        self.assertEqual(snapshot_worktree(self.source), before)

    def test_record_for_another_checkout_is_rejected(self) -> None:
        self.install_ok()
        state = self.fx.load_state()
        state["installation"]["target"]["root"] = str(self.root / "somewhere-else")
        self.fx.save_state(state)
        before = snapshot_worktree(self.source)
        with self.assertRaises(StateError):
            self.uninstall()
        self.assertEqual(snapshot_worktree(self.source), before)

    def test_bundle_path_traversal_is_rejected(self) -> None:
        manifest = read_manifest(self.bundle)
        manifest["files"][0]["upstreamPath"] = "../escape.txt"
        write_manifest(self.bundle, manifest)
        before = snapshot_worktree(self.source)
        with self.assertRaises(BundleError):
            self.install()
        self.assertEqual(snapshot_worktree(self.source), before)

    def test_corrupt_snapshot_is_rejected(self) -> None:
        snapshot = self.bundle / "changes" / "src" / "app.ts"
        snapshot.write_bytes(snapshot.read_bytes() + b"tampered\n")
        before = snapshot_worktree(self.source)
        with self.assertRaises(BundleError):
            self.install()
        self.assertEqual(snapshot_worktree(self.source), before)

    def test_manifest_and_patch_must_agree(self) -> None:
        manifest = read_manifest(self.bundle)
        extra_snapshot = self.bundle / "changes" / "docs" / "extra.md"
        extra_snapshot.write_bytes(b"extra\n")
        manifest["files"].append(
            {
                "upstreamPath": "docs/extra.md",
                "snapshotPath": "changes/docs/extra.md",
                "sha256": sha(b"extra\n"),
            }
        )
        write_manifest(self.bundle, manifest)
        with self.assertRaises(BundleError) as context:
            self.install()
        self.assertIn("disagree", str(context.exception))

    def test_patch_with_deletion_or_rename_is_rejected(self) -> None:
        cases = (
            (
                "deletion",
                b"diff --git a/docs/old.md b/docs/old.md\n"
                b"deleted file mode 100644\n",
                "delete",
            ),
            (
                "rename",
                b"diff --git a/docs/old.md b/docs/old.md\n"
                b"rename from docs/old.md\n"
                b"rename to docs/old.md\n",
                "rename",
            ),
            (
                "similarity",
                b"diff --git a/docs/old.md b/docs/old.md\n"
                b"similarity index 90%\n",
                "rename or copy",
            ),
        )
        for label, patch, expected in cases:
            with self.subTest(label=label):
                with self.assertRaises(BundleError) as context:
                    patch_affected_paths(patch)
                self.assertIn(expected, str(context.exception).lower())

    # ------------------------------------------------------------------
    # Locks and crash recovery
    # ------------------------------------------------------------------
    def test_live_lock_blocks_install(self) -> None:
        store = self.fx.store()
        store.base_dir.mkdir(parents=True)
        lock = {
            "formatVersion": 1,
            "pid": os.getpid(),
            "hostname": __import__("socket").gethostname(),
            "createdAt": "2026-01-01T00:00:00Z",
            "command": "other",
            "token": "x",
        }
        store.lock_path.write_text(json.dumps(lock), encoding="utf-8")
        before = snapshot_worktree(self.source)
        with self.assertRaises(LockError):
            self.install()
        self.assertEqual(snapshot_worktree(self.source), before)
        self.assertFalse(self.fx.state_path().exists())

    def test_dead_lock_is_reclaimed(self) -> None:
        store = self.fx.store()
        store.base_dir.mkdir(parents=True)
        store.lock_path.write_text(
            json.dumps(
                {
                    "formatVersion": 1,
                    "pid": 424242,
                    "hostname": __import__("socket").gethostname(),
                    "createdAt": "2026-01-01T00:00:00Z",
                    "command": "other",
                    "token": "x",
                }
            ),
            encoding="utf-8",
        )
        with mock.patch("orca_install.lock.pid_is_alive", return_value=False):
            result = self.install_ok()
        self.assertTrue(result.installation_id)
        self.assertFalse(store.lock_path.exists())

    def test_stale_lock_reclaim_does_not_steal_a_fresh_lock(self) -> None:
        store = self.fx.store()
        store.base_dir.mkdir(parents=True)
        stale = {
            "formatVersion": 1,
            "pid": 424242,
            "hostname": __import__("socket").gethostname(),
            "createdAt": "2026-01-01T00:00:00Z",
            "command": "stale",
            "token": "stale-token",
        }
        store.lock_path.write_text(json.dumps(stale), encoding="utf-8")
        first = InstallationLock(store, "first")
        second = InstallationLock(store, "second")

        with mock.patch("orca_install.lock.pid_is_alive", return_value=False):
            first.acquire()
            # Simulate a process that read the stale bytes before the first
            # process replaced them: its later unlink must not remove the live lock.
            second._read_lock = lambda: stale  # type: ignore[method-assign]
            with self.assertRaises(LockError) as context:
                second.acquire()

        self.assertIn("changed", str(context.exception).lower())
        self.assertTrue(first.acquired)
        self.assertFalse(second.acquired)
        current = json.loads(store.lock_path.read_text(encoding="utf-8"))
        self.assertEqual(current["token"], first.token)
        self.assertEqual(list(store.base_dir.glob("*.stale")), [])

        first.release()
        self.assertFalse(store.lock_path.exists())

    def test_uncertain_lock_owner_is_not_stolen(self) -> None:
        store = self.fx.store()
        store.base_dir.mkdir(parents=True)
        store.lock_path.write_text(
            json.dumps(
                {
                    "formatVersion": 1,
                    "pid": 424242,
                    "hostname": __import__("socket").gethostname(),
                    "createdAt": "2026-01-01T00:00:00Z",
                    "command": "other",
                    "token": "x",
                }
            ),
            encoding="utf-8",
        )
        with mock.patch("orca_install.lock.pid_is_alive", return_value=None):
            with self.assertRaises(LockError):
                self.install()
        self.assertTrue(store.lock_path.exists())
        self.assertFalse(self.fx.state_path().exists())

    def test_failed_write_rolls_back(self) -> None:
        original = installer.atomic_write_bytes
        calls = {"count": 0, "failed": False}

        def flaky(path, data, mode):
            calls["count"] += 1
            if not calls["failed"] and calls["count"] == 2:
                calls["failed"] = True
                raise OSError("injected write failure")
            return original(path, data, mode)

        with mock.patch.object(installer, "atomic_write_bytes", side_effect=flaky):
            with self.assertRaises(InstallationError) as context:
                self.install()
        self.assertIn("restored", str(context.exception))
        self.fx.assert_worktree_matches_base(self)
        self.assertEqual(self.fx.load_state()["installation"]["status"], "uninstalled")
        self.install_ok()

    def test_incomplete_rollback_is_reported_as_recovery_required(self) -> None:
        original = installer.atomic_write_bytes
        calls = {"count": 0, "failed": False}

        def flaky(path, data, mode):
            calls["count"] += 1
            if not calls["failed"] and calls["count"] == 2:
                calls["failed"] = True
                raise OSError("injected write failure")
            return original(path, data, mode)

        with mock.patch.object(installer, "atomic_write_bytes", side_effect=flaky):
            with mock.patch.object(
                installer, "_rollback", return_value=["injected rollback failure"]
            ):
                with self.assertRaises(RecoveryRequiredError) as context:
                    self.install()
        self.assertIn("rollback was incomplete", str(context.exception))
        self.assertEqual(
            self.fx.load_state()["installation"]["status"], "recovery_required"
        )
        report = self.status()
        self.assertEqual(report.outcome, "recovery required")
        self.assertIn("Last error", report.render())
        before = snapshot_worktree(self.source)
        with self.assertRaises(RecoveryRequiredError):
            self.install()
        with self.assertRaises(RecoveryRequiredError):
            self.uninstall()
        self.assertEqual(snapshot_worktree(self.source), before)

    def test_interrupted_install_is_reconciled_before_a_new_install(self) -> None:
        first = self.install_ok()
        state = self.fx.load_state()
        state["installation"]["status"] = "installing"
        state["installation"]["progress"]["phase"] = "writing"
        self.fx.save_state(state)
        self.fx.write("src/app.ts", b"partially written\n")

        with self.assertRaises(InterruptedOperationError) as context:
            self.install()
        self.assertIn("re-run", str(context.exception))
        self.fx.assert_worktree_matches_base(self)
        recovered = self.fx.load_state()["installation"]
        self.assertEqual(recovered["status"], "uninstalled")
        self.assertTrue(Path(first.backup_path).is_dir())
        self.assertEqual(len(recovered["recoveryArchives"]), 1)

        second = self.install_ok()
        self.assertNotEqual(second.installation_id, first.installation_id)
        self.assertTrue(Path(first.backup_path).is_dir())
        self.uninstall()
        self.fx.assert_worktree_matches_base(self)

    def test_interrupted_install_archives_post_crash_edit(self) -> None:
        self.install_ok()
        state = self.fx.load_state()
        state["installation"]["status"] = "installing"
        self.fx.save_state(state)
        self.fx.write("src/app.ts", b"post crash user edit\n")

        with self.assertRaises(InterruptedOperationError):
            self.install()

        record = self.fx.load_state()["installation"]
        self.assertEqual(record["status"], "uninstalled")
        self.assertEqual(len(record["recoveryArchives"]), 1)
        archive = Path(record["recoveryArchives"][0])
        manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
        entry = next(item for item in manifest["entries"] if item["path"] == "src/app.ts")
        self.assertEqual(entry["reason"], "unexpected-content-during-recovery")
        self.assertEqual(
            (archive / entry["archivedFile"]).read_bytes(), b"post crash user edit\n"
        )
        self.fx.assert_worktree_matches_base(self)

    def test_interrupted_uninstall_is_resumed(self) -> None:
        self.install_ok()
        state = self.fx.load_state()
        state["installation"]["status"] = "uninstalling"
        state["installation"]["progress"]["phase"] = "uninstalling"
        self.fx.save_state(state)

        result = self.uninstall()
        self.assertEqual(result.outcome, "uninstalled")
        self.fx.assert_worktree_matches_base(self)

    def test_uninstall_write_failure_can_be_resumed(self) -> None:
        self.install_ok()
        original = uninstaller.atomic_write_bytes

        def flaky(path, data, mode):
            raise OSError("injected restore failure")

        with mock.patch.object(uninstaller, "atomic_write_bytes", side_effect=flaky):
            with self.assertRaises(InstallationError) as context:
                self.uninstall()
        self.assertIn("re-run uninstall", str(context.exception))
        self.assertEqual(self.fx.load_state()["installation"]["status"], "uninstalling")
        self.assertEqual(uninstaller.atomic_write_bytes, original)
        result = self.uninstall()
        self.assertEqual(result.outcome, "uninstalled")
        self.fx.assert_worktree_matches_base(self)

    # ------------------------------------------------------------------
    # Path safety and linked worktrees
    # ------------------------------------------------------------------
    def test_symlinked_parent_is_rejected(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        try:
            os.symlink(outside, self.fx.path("newdir"), target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks are not available: {exc}")
        before = snapshot_worktree(self.source)
        with self.assertRaises(PathSafetyError):
            self.install()
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(snapshot_worktree(self.source), before)
        self.assertFalse(self.fx.state_path().exists())

    @unittest.skipUnless(os.name == "nt", "junction test is Windows-only")
    def test_junction_parent_is_rejected(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        link = self.fx.path("newdir")
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
            env=clean_git_env(),
        )
        if result.returncode != 0:
            self.skipTest("junctions are not available: " + result.stderr.decode("utf-8", "replace"))
        try:
            with self.assertRaises(PathSafetyError):
                self.install()
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            try:
                os.rmdir(link)
            except OSError:
                pass

    def test_linked_worktree_uses_its_own_git_data_dir(self) -> None:
        worktree = self.root / "orca-worktree"
        run_git(self.source, "worktree", "add", "--detach", str(worktree), "HEAD")
        try:
            result = installer.install(self.bundle, worktree)
            self.assertEqual(result.outcome, "installed")
            git_dir = Path(
                run_git(worktree, "rev-parse", "--absolute-git-dir").decode().strip()
            ).resolve()
            expected = git_dir / "orca-advanced-orchestration"
            self.assertTrue(Path(result.backup_path).resolve().is_relative_to(expected))
            self.assertEqual((worktree / "src" / "app.ts").read_bytes(), installer_patched_app())
            self.assertEqual(self.fx.read("src/app.ts"), self.fx.base["src/app.ts"])

            result = uninstaller.uninstall(worktree)
            self.assertEqual(result.outcome, "uninstalled")
            self.assertEqual(
                (worktree / "src" / "app.ts").read_bytes(), self.fx.base["src/app.ts"]
            )
        finally:
            run_git(self.source, "worktree", "remove", "--force", str(worktree), check=False)

    # ------------------------------------------------------------------
    # CLI and status text
    # ------------------------------------------------------------------
    def test_cli_end_to_end(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
            self.assertEqual(
                cli.main(["install", "--source", str(self.source), "--dry-run"], bundle_root=self.bundle),
                0,
            )
            self.assertIn("Dry run: install", stdout.getvalue())
            self.assertEqual(
                cli.main(["install", "--source", str(self.source)], bundle_root=self.bundle),
                0,
            )
            self.assertIn("Installation: installed", stdout.getvalue())
            stdout.seek(0)
            stdout.truncate(0)
            self.assertEqual(
                cli.main(["status", "--source", str(self.source)], bundle_root=self.bundle),
                0,
            )
            self.assertIn("Installation: installed", stdout.getvalue())
            self.assertEqual(
                cli.main(
                    ["uninstall", "--source", str(self.source), "--dry-run"],
                    bundle_root=self.bundle,
                ),
                0,
            )
            self.assertIn("Dry run: uninstall", stdout.getvalue())
            self.assertEqual(
                cli.main(["uninstall", "--source", str(self.source)], bundle_root=self.bundle),
                0,
            )
            self.assertIn("Installation: uninstalled", stdout.getvalue())
            self.assertEqual(
                cli.main(["uninstall", "--source", str(self.source)], bundle_root=self.bundle),
                0,
            )
            self.assertIn("Installation: not installed", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_reports_errors_with_exit_code(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
            code = cli.main(
                ["install", "--source", str(self.root / "missing")], bundle_root=self.bundle
            )
        self.assertEqual(code, 1)
        self.assertIn("error:", stderr.getvalue())
        self.assertIn("does not exist", stderr.getvalue())

    def test_status_lists_modified_files(self) -> None:
        self.install_ok()
        self.fx.write("src/app.ts", b"changed\n")
        self.fx.path("src/new.ts").unlink()
        report = self.status()
        self.assertEqual(report.comparison.modified, ["src/app.ts"])
        self.assertEqual(report.comparison.missing, ["src/new.ts"])
        rendered = report.render()
        self.assertIn("Modified since install", rendered)
        self.assertIn("src/app.ts", rendered)

    def test_powershell_installer_verify_action(self) -> None:
        script = REPO_ROOT / "install.ps1"
        self.assertTrue(script.is_file())
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("PowerShell is not available")
        result = subprocess.run(
            [
                shell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Action",
                "verify",
                "-NoPause",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Verified 79 files", result.stdout)

    def test_readme_local_links_resolve(self) -> None:
        for readme in ("README.md", "README.en.md", "docs/DESIGN.md", "docs/VALIDATION.md"):
            document = REPO_ROOT / readme
            text = document.read_text(encoding="utf-8")
            for match in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
                target = match.split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                with self.subTest(readme=readme, link=target):
                    self.assertTrue((document.parent / target).exists(), f"Broken link: {target}")


def installer_patched_app() -> bytes:
    from helpers import APP_PATCHED

    return APP_PATCHED.encode()


if __name__ == "__main__":
    unittest.main()
