"""PowerShell bootstrap tests that do not require network access."""

from __future__ import annotations

from pathlib import Path
import functools
import http.server
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest

from helpers import (
    REPO_ROOT,
    build_fixture,
    make_version_bundle,
    read_manifest,
    run_git,
    snapshot_worktree,
    write_manifest,
)

POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def prepare_package(fixture) -> None:
    shutil.copytree(REPO_ROOT / "scripts", fixture.bundle / "scripts", dirs_exist_ok=True)
    shutil.copy2(REPO_ROOT / "install.ps1", fixture.bundle / "install.ps1")


def run_powershell(
    arguments,
    cwd: Path,
    local_app_data: Path,
    path_prefix: Path | None = None,
    extra_env: dict | None = None,
):
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(local_app_data)
    if path_prefix is not None:
        env["PATH"] = str(path_prefix) + os.pathsep + env.get("PATH", "")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", *arguments],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        errors="replace",
        env=env,
        timeout=180,
    )


@unittest.skipUnless(os.name == "nt", "PowerShell bootstrap tests run on Windows")
@unittest.skipUnless(POWERSHELL, "PowerShell is not available")
class PowerShellBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="orca-ps-test-")
        self.root = Path(self.temp.name)
        self.fx = build_fixture(self.root)
        prepare_package(self.fx)
        self.local_app_data = self.root / "localappdata"
        self.outside = self.root / "outside"
        self.outside.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_local_package_actions_from_outside_repository(self) -> None:
        before = snapshot_worktree(self.fx.source)
        install = run_powershell(
            [
                "-File",
                str(REPO_ROOT / "install.ps1"),
                "-Action",
                "install",
                "-RepoRoot",
                str(self.fx.bundle),
                "-Source",
                str(self.fx.source),
                "-NoPause",
            ],
            self.outside,
            self.local_app_data,
        )
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        self.assertIn("Installation: installed", install.stdout)
        self.assertIn("pnpm build", install.stdout)
        self.assertIn("Uygulama", install.stdout)
        self.assertNotEqual(snapshot_worktree(self.fx.source), before)

        status = run_powershell(
            [
                "-File",
                str(REPO_ROOT / "install.ps1"),
                "-Action",
                "status",
                "-RepoRoot",
                str(self.fx.bundle),
                "-Source",
                str(self.fx.source),
                "-NoPause",
            ],
            self.outside,
            self.local_app_data,
        )
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        self.assertIn("Package: 1.0.0", status.stdout)
        self.assertIn("Managed files: 7 total", status.stdout)

        uninstall = run_powershell(
            [
                "-File",
                str(REPO_ROOT / "install.ps1"),
                "-Action",
                "uninstall",
                "-RepoRoot",
                str(self.fx.bundle),
                "-Source",
                str(self.fx.source),
                "-NoPause",
            ],
            self.outside,
            self.local_app_data,
        )
        self.assertEqual(uninstall.returncode, 0, uninstall.stdout + uninstall.stderr)
        self.assertIn("Installation: uninstalled", uninstall.stdout)
        self.assertEqual(snapshot_worktree(self.fx.source), before)

    def test_python_resolution_falls_back_after_stderr(self) -> None:
        fakebin = self.root / "fakebin"
        fakebin.mkdir()
        (fakebin / "py.cmd").write_text(
            "@echo off\r\necho injected probe failure 1>&2\r\nexit /b 1\r\n",
            encoding="ascii",
        )
        result = run_powershell(
            [
                "-File",
                str(REPO_ROOT / "install.ps1"),
                "-Action",
                "verify",
                "-RepoRoot",
                str(REPO_ROOT),
                "-NoPause",
            ],
            self.outside,
            self.local_app_data,
            path_prefix=fakebin,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Verified 135 files", result.stdout)

    def test_temporary_local_bundle_path_is_persisted(self) -> None:
        run_powershell(
            [
                "-File",
                str(REPO_ROOT / "install.ps1"),
                "-Action",
                "status",
                "-RepoRoot",
                str(self.fx.bundle),
                "-Source",
                str(self.fx.source),
                "-NoPause",
            ],
            self.outside,
            self.local_app_data,
        )
        config = self.local_app_data / "OrcaAdvancedOrchestration" / "config.json"
        self.assertTrue(config.is_file())
        config_data = json.loads(config.read_text(encoding="utf-8-sig"))
        self.assertEqual(config_data["source"], str(self.fx.source))

        second = run_powershell(
            [
                "-File",
                str(REPO_ROOT / "install.ps1"),
                "-Action",
                "status",
                "-RepoRoot",
                str(self.fx.bundle),
                "-NoPause",
            ],
            self.outside,
            self.local_app_data,
        )
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn(str(self.fx.source), second.stdout)

    def make_isolated_bundle(self):
        isolated = self.root / "isolated"
        bundle = isolated / "bundle"
        shutil.copytree(self.fx.bundle, bundle)
        shutil.copytree(REPO_ROOT / "scripts", bundle / "scripts", dirs_exist_ok=True)
        shutil.copy2(REPO_ROOT / "install.ps1", bundle / "install.ps1")
        cwd = isolated / "cwd"
        cwd.mkdir(parents=True)
        return bundle, cwd

    def test_missing_source_is_cloned_automatically(self) -> None:
        bundle, cwd = self.make_isolated_bundle()
        manifest = read_manifest(bundle)
        manifest["upstream"]["repository"] = str(self.fx.source)
        write_manifest(bundle, manifest)
        run_git(self.fx.source, "tag", "-f", "vtest", self.fx.base_commit)

        home = self.root / "home"
        home.mkdir()
        extra_env = {"USERPROFILE": str(home), "HOME": str(home)}

        install = run_powershell(
            [
                "-File",
                str(REPO_ROOT / "install.ps1"),
                "-Action",
                "install",
                "-RepoRoot",
                str(bundle),
                "-NoPause",
            ],
            cwd,
            self.local_app_data,
            extra_env=extra_env,
        )
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        self.assertIn("otomatik klonlanacak", install.stdout)
        cloned = home / "orca-dev"
        self.assertTrue((cloned / "src" / "app.ts").is_file(), install.stdout)
        self.assertIn("Installation: installed", install.stdout)

        config = json.loads(
            (self.local_app_data / "OrcaAdvancedOrchestration" / "config.json").read_text(
                encoding="utf-8-sig"
            )
        )
        self.assertEqual(config["source"], str(cloned))

        status = run_powershell(
            [
                "-File",
                str(REPO_ROOT / "install.ps1"),
                "-Action",
                "status",
                "-RepoRoot",
                str(bundle),
                "-NoPause",
            ],
            cwd,
            self.local_app_data,
            extra_env=extra_env,
        )
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        self.assertIn(str(cloned), status.stdout)
        self.assertIn("Package: 1.0.0", status.stdout)

    def test_existing_source_is_discovered_automatically(self) -> None:
        bundle, cwd = self.make_isolated_bundle()
        home = self.root / "home"
        checkout = home / "src" / "my-orca"
        checkout.mkdir(parents=True)
        (checkout / "package.json").write_text(
            '{"name": "orca", "version": "1.4.246"}\n', encoding="utf-8"
        )
        run_git(checkout, "init", "-q")
        run_git(checkout, "config", "user.email", "installer-test@example.invalid")
        run_git(checkout, "config", "user.name", "Installer Test")
        run_git(checkout, "add", "-A")
        run_git(checkout, "commit", "-qm", "source")
        extra_env = {"USERPROFILE": str(home), "HOME": str(home)}

        status = run_powershell(
            [
                "-File",
                str(REPO_ROOT / "install.ps1"),
                "-Action",
                "status",
                "-RepoRoot",
                str(bundle),
                "-NoPause",
            ],
            cwd,
            self.local_app_data,
            extra_env=extra_env,
        )
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        self.assertIn("otomatik bulundu", status.stdout)
        self.assertIn(str(checkout), status.stdout)
        self.assertIn("Installation: not installed", status.stdout)

        config = json.loads(
            (self.local_app_data / "OrcaAdvancedOrchestration" / "config.json").read_text(
                encoding="utf-8-sig"
            )
        )
        self.assertEqual(config["source"], str(checkout))

    def write_config(self, payload: dict) -> Path:
        config = self.local_app_data / "OrcaAdvancedOrchestration" / "config.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps(payload), encoding="utf-8")
        return config

    def run_status(self, bundle, cwd, extra_env=None, extra_args=()):
        return run_powershell(
            [
                "-File",
                str(REPO_ROOT / "install.ps1"),
                "-Action",
                "status",
                "-RepoRoot",
                str(bundle),
                "-NoPause",
                *extra_args,
            ],
            cwd,
            self.local_app_data,
            extra_env=extra_env,
        )

    def test_invalid_explicit_source_does_not_fall_back(self) -> None:
        bundle, cwd = self.make_isolated_bundle()
        home = self.root / "home"
        discoverable = home / "src" / "my-orca"
        discoverable.mkdir(parents=True)
        (discoverable / "package.json").write_text('{"name": "orca"}\n', encoding="utf-8")
        run_git(discoverable, "init", "-q")
        run_git(discoverable, "config", "user.email", "installer-test@example.invalid")
        run_git(discoverable, "config", "user.name", "Installer Test")
        run_git(discoverable, "add", "-A")
        run_git(discoverable, "commit", "-qm", "source")
        extra_env = {"USERPROFILE": str(home), "HOME": str(home)}

        missing = self.root / "typo"
        install = run_powershell(
            [
                "-File",
                str(REPO_ROOT / "install.ps1"),
                "-Action",
                "install",
                "-RepoRoot",
                str(bundle),
                "-Source",
                str(missing),
                "-NoPause",
            ],
            cwd,
            self.local_app_data,
            extra_env=extra_env,
        )
        self.assertNotEqual(install.returncode, 0, install.stdout + install.stderr)
        self.assertIn("-Source yolu bulunamadi", install.stdout)
        self.assertNotIn("otomatik bulundu", install.stdout)
        self.assertNotIn("Installation: installed", install.stdout)
        self.assertFalse((home / "orca-dev").exists())
        self.assertFalse((discoverable / "src" / "app.ts").exists())
        config = self.local_app_data / "OrcaAdvancedOrchestration" / "config.json"
        self.assertFalse(
            config.is_file() and "source" in json.loads(config.read_text(encoding="utf-8-sig")),
            install.stdout,
        )

        plain = self.root / "plain"
        plain.mkdir()
        status = self.run_status(bundle, cwd, extra_env, ("-Source", str(plain)))
        self.assertNotEqual(status.returncode, 0, status.stdout + status.stderr)
        self.assertIn("-Source yolu bir Orca Git checkout koku degil", status.stdout)

    def test_configured_language_is_used(self) -> None:
        self.write_config({"lang": "en"})
        status = self.run_status(self.fx.bundle, self.outside, None, ("-Source", str(self.fx.source)))
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        self.assertIn("Versions", status.stdout)
        self.assertNotIn("Surumler", status.stdout)
        config = json.loads(
            (self.local_app_data / "OrcaAdvancedOrchestration" / "config.json").read_text(
                encoding="utf-8-sig"
            )
        )
        self.assertEqual(config["lang"], "en")

    def test_lang_flag_uses_english_without_persisting(self) -> None:
        status = self.run_status(
            self.fx.bundle, self.outside, None, ("-Source", str(self.fx.source), "-Lang", "en")
        )
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        self.assertIn("Versions", status.stdout)
        self.assertNotIn("Surumler", status.stdout)
        config = json.loads(
            (self.local_app_data / "OrcaAdvancedOrchestration" / "config.json").read_text(
                encoding="utf-8-sig"
            )
        )
        self.assertNotIn("lang", config)

    def test_unavailable_saved_source_is_kept_in_config(self) -> None:
        missing = self.root / "gone"
        self.write_config({"source": str(missing), "lang": "en"})
        home = self.root / "home"
        checkout = home / "src" / "my-orca"
        checkout.mkdir(parents=True)
        (checkout / "package.json").write_text('{"name": "orca"}\n', encoding="utf-8")
        run_git(checkout, "init", "-q")
        run_git(checkout, "config", "user.email", "installer-test@example.invalid")
        run_git(checkout, "config", "user.name", "Installer Test")
        run_git(checkout, "add", "-A")
        run_git(checkout, "commit", "-qm", "source")
        status = self.run_status(
            self.fx.bundle, self.outside, {"USERPROFILE": str(home), "HOME": str(home)}
        )
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        self.assertIn("ignoring it for this run", status.stdout)
        self.assertIn("Found Orca source automatically", status.stdout)
        config = json.loads(
            (self.local_app_data / "OrcaAdvancedOrchestration" / "config.json").read_text(
                encoding="utf-8-sig"
            )
        )
        self.assertEqual(config["source"], str(missing))
        self.assertEqual(config["lang"], "en")

    def test_multiple_discovered_sources_warn_and_pick_first(self) -> None:
        bundle, cwd = self.make_isolated_bundle()
        home = self.root / "home"
        for name in ("a-orca", "b-orca"):
            checkout = home / "src" / name
            checkout.mkdir(parents=True)
            (checkout / "package.json").write_text('{"name": "orca"}\n', encoding="utf-8")
            run_git(checkout, "init", "-q")
            run_git(checkout, "config", "user.email", "installer-test@example.invalid")
            run_git(checkout, "config", "user.name", "Installer Test")
            run_git(checkout, "add", "-A")
            run_git(checkout, "commit", "-qm", "source")
        extra_env = {"USERPROFILE": str(home), "HOME": str(home)}

        status = self.run_status(bundle, cwd, extra_env)
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        self.assertIn("Birden fazla Orca kaynagi", status.stdout)
        self.assertIn("uyusmuyor", status.stdout)
        self.assertNotIn("Secim [Enter=1]", status.stdout)
        config = json.loads(
            (self.local_app_data / "OrcaAdvancedOrchestration" / "config.json").read_text(
                encoding="utf-8-sig"
            )
        )
        self.assertIn(config["source"], {str(home / "src" / "a-orca"), str(home / "src" / "b-orca")})
        self.assertIn(config["source"], status.stdout)

    def test_local_update_same_version_different_content_reaches_python_check(self) -> None:
        install = run_powershell(
            [
                "-File",
                str(REPO_ROOT / "install.ps1"),
                "-Action",
                "install",
                "-RepoRoot",
                str(self.fx.bundle),
                "-Source",
                str(self.fx.source),
                "-NoPause",
            ],
            self.outside,
            self.local_app_data,
        )
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)

        same_version = make_version_bundle(
            self.fx, "1.0.0", modify={"src/app.ts": b"same version, different content\n"}
        )
        shutil.copytree(
            REPO_ROOT / "scripts", same_version / "scripts", dirs_exist_ok=True
        )
        shutil.copy2(REPO_ROOT / "install.ps1", same_version / "install.ps1")
        before = snapshot_worktree(self.fx.source)

        update = run_powershell(
            [
                "-File",
                str(REPO_ROOT / "install.ps1"),
                "-Action",
                "update",
                "-RepoRoot",
                str(same_version),
                "-Source",
                str(self.fx.source),
                "-NoPause",
            ],
            self.outside,
            self.local_app_data,
        )
        self.assertNotEqual(update.returncode, 0, update.stdout + update.stderr)
        self.assertIn("different content", update.stdout + update.stderr)
        self.assertEqual(snapshot_worktree(self.fx.source), before)

    def test_remote_mode_uses_verified_cache_offline(self) -> None:
        cache = self.local_app_data / "OrcaAdvancedOrchestration" / "packages" / "1.0.0"
        shutil.copytree(self.fx.bundle, cache)
        (cache / ".verified").write_text("0" * 64, encoding="ascii")
        remote = self.root / "remote"
        remote.mkdir()
        shutil.copy2(REPO_ROOT / "install.ps1", remote / "install.ps1")

        install = run_powershell(
            [
                "-File",
                str(remote / "install.ps1"),
                "-Action",
                "install",
                "-Version",
                "1.0.0",
                "-Source",
                str(self.fx.source),
                "-NoPause",
            ],
            remote,
            self.local_app_data,
        )
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        self.assertIn("Installation: installed", install.stdout)
        self.assertIn("1.0.0", install.stdout)

        no_op = run_powershell(
            [
                "-File",
                str(remote / "install.ps1"),
                "-Action",
                "update",
                "-Version",
                "1.0.0",
                "-Source",
                str(self.fx.source),
                "-NoPause",
            ],
            remote,
            self.local_app_data,
        )
        self.assertEqual(no_op.returncode, 0, no_op.stdout + no_op.stderr)
        self.assertIn("Update: already up to date", no_op.stdout)
        self.assertIn("Zaten g", no_op.stdout)
        self.assertNotIn("pnpm build", no_op.stdout)

        uninstall = run_powershell(
            [
                "-File",
                str(remote / "install.ps1"),
                "-Action",
                "uninstall",
                "-Source",
                str(self.fx.source),
                "-NoPause",
            ],
            remote,
            self.local_app_data,
        )
        self.assertEqual(uninstall.returncode, 0, uninstall.stdout + uninstall.stderr)
        self.assertIn("Installation: uninstalled", uninstall.stdout)
        self.fx.assert_worktree_matches_base(self)

    def test_scriptblock_invocation_does_not_exit_the_caller(self) -> None:
        script = str(REPO_ROOT / "install.ps1").replace("'", "''")
        repo = str(REPO_ROOT).replace("'", "''")
        command = (
            f"$code = Get-Content -LiteralPath '{script}' -Raw; "
            f"& ([scriptblock]::Create($code)) -Action verify -RepoRoot '{repo}' -NoPause; "
            "Write-Output 'AFTER_SCRIPTBLOCK'"
        )
        result = run_powershell(["-Command", command], self.outside, self.local_app_data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Verified 135 files", result.stdout)
        self.assertIn("AFTER_SCRIPTBLOCK", result.stdout)

    def test_semver_prerelease_ordering(self) -> None:
        script = str(REPO_ROOT / "install.ps1").replace("'", "''")
        repo = str(REPO_ROOT).replace("'", "''")
        checks = (
            "$rc1 = Compare-VersionValue '1.0.0-rc1' '1.0.0'; "
            "$stable = Compare-VersionValue '1.0.0' '1.0.0-rc1'; "
            "$equal = Compare-VersionValue '1.0.0' '1.0.0'; "
            "$serial = Compare-VersionValue '1.0.0-rc.2' '1.0.0-rc.10'; "
            "$alpha = Compare-VersionValue '1.0.0-alpha' '1.0.0-alpha.1'; "
            "$numeric = Compare-VersionValue '1.0.0-alpha.1' '1.0.0-alpha.beta'; "
            "Write-Output \"CMP=$rc1,$stable,$equal,$serial,$alpha,$numeric\""
        )
        command = (
            f"$code = Get-Content -LiteralPath '{script}' -Raw; "
            f"$append = @'\n{checks}\n'@; "
            "$code += \"`n\" + $append; "
            f"& ([scriptblock]::Create($code)) -Action verify -RepoRoot '{repo}' -NoPause"
        )
        result = run_powershell(["-Command", command], self.outside, self.local_app_data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("CMP=-1,1,0,-1,-1,-1", result.stdout)

    def test_irm_pipe_to_iex_opens_and_exits_cleanly(self) -> None:
        web_root = self.root / "web"
        web_root.mkdir()
        shutil.copy2(REPO_ROOT / "install.ps1", web_root / "install.ps1")

        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

        handler = functools.partial(QuietHandler, directory=str(web_root))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/install.ps1"
            env = os.environ.copy()
            env["LOCALAPPDATA"] = str(self.local_app_data)
            command = f"irm {url} | iex; Write-Output 'AFTER_IRM'"
            result = subprocess.run(
                [
                    POWERSHELL,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                cwd=str(self.outside),
                input="0\n",
                capture_output=True,
                text=True,
                errors="replace",
                env=env,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Orca Advanced Orchestration", result.stdout)
            self.assertIn("AFTER_IRM", result.stdout)
            self.assertNotIn("Missing closing", result.stderr)
            self.assertNotIn("Unexpected attribute", result.stderr)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
