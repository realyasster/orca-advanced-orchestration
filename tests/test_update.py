"""Transactional update tests: no-op, preflight, rollback, and interruption."""

from __future__ import annotations

from pathlib import Path
from unittest import mock
import hashlib
import json
import tempfile
import unittest

from helpers import (
    build_fixture,
    make_version_bundle,
    snapshot_worktree,
)

from orca_install import backup as backup_module, installer, uninstaller, updater
from orca_install.backup import load_backup
from orca_install.errors import InstallationError, InterruptedOperationError
from orca_install.gitutil import resolve_checkout
from orca_install.status import collect_status, verify_installation
from orca_install.store import Store, StoreState


class UpdateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="orca-ao-update-")
        self.root = Path(self.temp.name)
        self.fx = build_fixture(self.root)
        self.source = self.fx.source
        self.v2 = make_version_bundle(
            self.fx,
            "1.1.0",
            modify={"src/app.ts": b"v2 app content\n"},
            add={"src/extra.ts": b"v2 extra\n"},
            remove=["docs/readme.md"],
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def install(self):
        result = installer.install(self.fx.bundle, self.source)
        self.assertEqual(result.outcome, "installed")
        return result

    def installed_bytes(self) -> dict:
        return {
            rel: self.fx.read(rel)
            for rel in self.fx.managed
            if self.fx.path(rel).is_file()
        }

    def test_clean_update_then_uninstall_restores_base(self) -> None:
        first = self.install()
        first_backup = Path(first.backup_path)
        v1_bytes = self.installed_bytes()

        result = updater.update(self.v2, self.source)
        self.assertEqual(result.outcome, "updated")
        self.assertEqual(result.from_version, "1.0.0")
        self.assertEqual(result.to_version, "1.1.0")
        self.assertEqual(result.updated, 4)
        self.assertEqual(result.added, 3)
        self.assertEqual(result.removed, 1)
        self.assertEqual(self.fx.read("src/app.ts"), b"v2 app content\n")
        self.assertEqual(self.fx.read("src/extra.ts"), b"v2 extra\n")
        self.assertNotEqual(self.fx.read("docs/readme.md"), v1_bytes["docs/readme.md"])
        self.assertTrue(first_backup.is_dir(), "the first original backup must be preserved")

        store = self.fx.store()
        record = self.fx.load_state()["installation"]
        install_dir = store.install_dir(record["installationId"])
        self.assertFalse((install_dir / "updates").exists())
        active_backup = Path(result.backup_path)
        self.assertTrue(active_backup.is_dir())
        self.assertTrue(active_backup.name.startswith("backup-"))
        backup_manifest = json.loads(
            (active_backup / "manifest.json").read_text(encoding="utf-8")
        )
        retired = {entry["path"]: entry for entry in backup_manifest["retiredEntries"]}
        self.assertTrue(retired["docs/readme.md"]["existed"])
        self.assertEqual(
            (active_backup / retired["docs/readme.md"]["backupFile"]).read_bytes(),
            self.fx.base["docs/readme.md"],
        )

        report = collect_status(self.source)
        self.assertEqual(report.outcome, "installed")
        self.assertEqual(report.record.package_version, "1.1.0")
        self.assertTrue(report.comparison.clean)

        undone = uninstaller.uninstall(self.source)
        self.assertEqual(undone.outcome, "uninstalled")
        self.fx.assert_worktree_matches_base(self)
        self.assertFalse(self.fx.path("src/extra.ts").exists())

    def test_same_package_is_noop_without_writing_state(self) -> None:
        self.install()
        before = self.fx.state_path().read_bytes()
        result = updater.update(self.fx.bundle, self.source)
        self.assertEqual(result.outcome, "no-op")
        self.assertEqual(self.fx.state_path().read_bytes(), before)

    def test_same_version_with_different_content_is_rejected(self) -> None:
        self.install()
        same_version = make_version_bundle(
            self.fx, "1.0.0", modify={"src/app.ts": b"repacked content\n"}
        )
        before = snapshot_worktree(self.source)
        with self.assertRaises(InstallationError) as context:
            updater.update(same_version, self.source)
        self.assertIn("different content", str(context.exception))
        self.assertEqual(snapshot_worktree(self.source), before)

    def test_local_changes_block_update_before_writing(self) -> None:
        self.install()
        self.fx.write("src/app.ts", b"local edit after install\n")
        before = snapshot_worktree(self.source)
        with self.assertRaises(InstallationError) as context:
            updater.update(self.v2, self.source)
        self.assertIn("Local changes", str(context.exception))
        self.assertEqual(snapshot_worktree(self.source), before)
        self.assertEqual(collect_status(self.source).record.package_version, "1.0.0")

    def test_upstream_base_change_is_refused_without_reset(self) -> None:
        self.install()
        head_before = self.fx.path(".git").exists()
        other = make_version_bundle(
            self.fx, "1.2.0", base_commit="0" * 40
        )
        with self.assertRaises(InstallationError) as context:
            updater.update(other, self.source)
        message = str(context.exception)
        self.assertIn("never runs git reset", message)
        self.assertEqual(collect_status(self.source).record.package_version, "1.0.0")
        self.assertTrue(head_before)

    def test_dry_run_changes_nothing(self) -> None:
        self.install()
        before = snapshot_worktree(self.source)
        state_before = self.fx.state_path().read_bytes()
        result = updater.update(self.v2, self.source, dry_run=True)
        self.assertEqual(result.outcome, "dry-run")
        self.assertEqual(result.to_version, "1.1.0")
        self.assertEqual(snapshot_worktree(self.source), before)
        self.assertEqual(self.fx.state_path().read_bytes(), state_before)

    def test_failed_update_restores_previous_installed_version(self) -> None:
        self.install()
        v1_bytes = self.installed_bytes()
        original = updater.atomic_write_bytes
        failed = {"value": False}

        def flaky(path, data, mode):
            if not failed["value"] and Path(path) == self.fx.path("src/app.ts"):
                failed["value"] = True
                raise OSError("injected update failure")
            return original(path, data, mode)

        with mock.patch.object(updater, "atomic_write_bytes", side_effect=flaky):
            with self.assertRaises(InstallationError) as context:
                updater.update(self.v2, self.source)
        self.assertIn("previous installed version was restored", str(context.exception))
        for rel, data in v1_bytes.items():
            self.assertEqual(self.fx.read(rel), data, rel)
        self.assertFalse(self.fx.path("src/extra.ts").exists())
        record = self.fx.load_state()["installation"]
        self.assertEqual(record["status"], "installed")
        self.assertEqual(record["package"]["version"], "1.0.0")
        install_dir = self.fx.store().install_dir(record["installationId"])
        self.assertFalse((install_dir / "updates").exists())
        self.assertEqual(list(install_dir.glob("backup-*")), [])

    def test_interrupted_update_is_rolled_back_with_archive(self) -> None:
        self.install()
        v1_bytes = self.installed_bytes()
        checkout = resolve_checkout(self.source)
        store = Store(checkout)
        state = store.load()
        record = state.installation
        assert record is not None
        bundle = updater.load_bundle(self.v2)
        backup = load_backup(store, record)
        plan = updater._build_plan(checkout, bundle, record, backup)
        targets = {item.path: item.sha256 for item in plan.files}
        for item in plan.removed:
            if item.original_existed:
                data, _ = backup.read(item.path)
                targets[item.path] = hashlib.sha256(data).hexdigest()
            else:
                targets[item.path] = None
        for rel in plan.previous_entries:
            targets.setdefault(rel, None)
        update_id = "manual-update"
        updater._write_previous_snapshot(
            store, record, update_id, plan, record.to_dict(), targets
        )
        record.status = "updating"
        record.update_id = update_id
        record.progress.phase = "updating"
        store.save(StoreState(installation=record, history=state.history))

        self.fx.write("src/app.ts", b"post crash user edit\n")
        with self.assertRaises(InterruptedOperationError):
            updater.update(self.v2, self.source)

        record = self.fx.load_state()["installation"]
        self.assertEqual(record["status"], "installed")
        self.assertEqual(record["package"]["version"], "1.0.0")
        self.assertEqual(len(record["recoveryArchives"]), 1)
        archive = Path(record["recoveryArchives"][0])
        manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
        entry = next(item for item in manifest["entries"] if item["path"] == "src/app.ts")
        self.assertEqual(entry["reason"], "unexpected-content-during-update-recovery")
        self.assertEqual(
            (archive / entry["archivedFile"]).read_bytes(), b"post crash user edit\n"
        )
        for rel, data in v1_bytes.items():
            self.assertEqual(self.fx.read(rel), data, rel)
        self.assertFalse(self.fx.path("src/extra.ts").exists())
        install_dir = self.fx.store().install_dir(record["installationId"])
        self.assertFalse((install_dir / "updates").exists())
        self.assertEqual(list(install_dir.glob("backup-*")), [])

    def test_update_requires_an_active_installation(self) -> None:
        with self.assertRaises(InstallationError) as context:
            updater.update(self.v2, self.source)
        self.assertIn("install instead", str(context.exception))

    def test_added_upstream_file_is_backed_up_as_original(self) -> None:
        self.install()
        # The new package manages an unmanaged upstream file. It must be
        # captured as an original so uninstall restores it.
        extra = self.fx.path("unrelated/extra-base.txt")
        extra.write_bytes(b"base content\n")
        v2 = make_version_bundle(
            self.fx, "1.1.0", add={"unrelated/extra-base.txt": b"patched content\n"}
        )
        updater.update(v2, self.source)
        self.assertEqual(self.fx.read("unrelated/extra-base.txt"), b"patched content\n")
        uninstaller.uninstall(self.source)
        self.assertEqual(self.fx.read("unrelated/extra-base.txt"), b"base content\n")

    def test_removed_managed_file_cleans_empty_created_directories(self) -> None:
        self.install()
        self.assertTrue(self.fx.path("newdir/created").is_dir())
        v2 = make_version_bundle(
            self.fx, "1.1.0", remove=["newdir/created/file.txt"]
        )
        updater.update(v2, self.source)
        self.assertFalse(self.fx.path("newdir/created").exists())
        self.assertFalse(self.fx.path("newdir").exists())
        uninstaller.uninstall(self.source)
        self.fx.assert_worktree_matches_base(self)

    def test_verify_reports_interrupted_states(self) -> None:
        self.install()
        for status in ("installing", "updating", "uninstalling"):
            with self.subTest(status=status):
                state = self.fx.load_state()
                state["installation"]["status"] = status
                self.fx.save_state(state)
                report = verify_installation(self.source)
                self.assertEqual(report.outcome, status)
                self.assertTrue(
                    any("interrupted operation" in item for item in report.problems),
                    report.problems,
                )

    def test_carried_backup_removes_its_directory_on_failure(self) -> None:
        self.install()
        checkout = resolve_checkout(self.source)
        store = Store(checkout)
        record = store.load().installation
        assert record is not None
        directory_name = "backup-injected-failure"
        entries = [
            {
                "path": "src/app.ts",
                "existed": True,
                "data": b"backup bytes\n",
                "mode": 0o644,
            }
        ]
        with mock.patch.object(
            backup_module, "atomic_write_bytes", side_effect=OSError("injected")
        ):
            with self.assertRaises(OSError):
                backup_module.write_carried_backup(
                    store,
                    checkout,
                    record.installation_id,
                    "fingerprint",
                    entries,
                    directory_name,
                )
        self.assertFalse(
            (store.install_dir(record.installation_id) / directory_name).exists()
        )


if __name__ == "__main__":
    unittest.main()
