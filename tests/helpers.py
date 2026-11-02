"""Shared helpers for the installer test suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def clean_git_env() -> dict:
    env = os.environ.copy()
    # Some agent shells export a malformed GIT_CONFIG_COUNT. Do not let that
    # break fixture Git commands or the installer subprocesses.
    for key in list(env):
        if key.startswith("GIT_CONFIG_"):
            env.pop(key, None)
    env.update(
        {
            "GIT_AUTHOR_NAME": "Installer Test",
            "GIT_AUTHOR_EMAIL": "installer-test@example.invalid",
            "GIT_COMMITTER_NAME": "Installer Test",
            "GIT_COMMITTER_EMAIL": "installer-test@example.invalid",
            "GIT_AUTHOR_DATE": "2020-01-01T00:00:00+0000",
            "GIT_COMMITTER_DATE": "2020-01-01T00:00:00+0000",
        }
    )
    return env


def run_git(cwd: Path, *args: str, check: bool = True) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=clean_git_env(),
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {cwd}: "
            f"{result.stderr.decode('utf-8', 'replace')}"
        )
    return result.stdout


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot_tree(root: Path, include_git: bool = True) -> dict:
    """Return a content snapshot for read-only assertions."""

    result = {"files": {}, "dirs": set(), "links": {}}
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        rel_dir = current_path.relative_to(root)
        if not include_git and rel_dir.parts and rel_dir.parts[0] == ".git":
            dirs[:] = []
            continue
        for name in list(dirs):
            full = current_path / name
            rel = full.relative_to(root).as_posix()
            if not include_git and rel.startswith(".git/"):
                continue
            if full.is_symlink():
                result["links"][rel] = os.readlink(full)
                dirs.remove(name)
            else:
                result["dirs"].add(rel)
        for name in files:
            full = current_path / name
            rel = full.relative_to(root).as_posix()
            if not include_git and rel.startswith(".git/"):
                continue
            if full.is_symlink():
                result["links"][rel] = os.readlink(full)
            else:
                result["files"][rel] = sha(full.read_bytes())
    return result


def snapshot_worktree(root: Path) -> dict:
    return snapshot_tree(root, include_git=False)


@dataclass
class Fixture:
    root: Path
    source: Path
    bundle: Path
    base_commit: str
    base: Dict[str, bytes] = field(default_factory=dict)
    base_modes: Dict[str, int] = field(default_factory=dict)
    managed: List[str] = field(default_factory=list)
    added: List[str] = field(default_factory=list)
    updated: List[str] = field(default_factory=list)

    def path(self, rel: str) -> Path:
        return self.source.joinpath(*rel.split("/"))

    def write(self, rel: str, data: bytes, mode: Optional[int] = None) -> None:
        path = self.path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if mode is not None:
            os.chmod(path, mode)

    def read(self, rel: str) -> bytes:
        return self.path(rel).read_bytes()

    def state_path(self) -> Path:
        return self.source / ".git" / "orca-advanced-orchestration" / "state.json"

    def data_dir(self) -> Path:
        return self.source / ".git" / "orca-advanced-orchestration"

    def store(self):
        from orca_install.gitutil import resolve_checkout
        from orca_install.store import Store

        return Store(resolve_checkout(self.source))

    def load_state(self) -> dict:
        return json.loads(self.state_path().read_text(encoding="utf-8"))

    def save_state(self, data: dict) -> None:
        self.state_path().write_text(json.dumps(data, indent=2), encoding="utf-8")

    def assert_worktree_matches_base(self, testcase) -> None:
        for rel, data in self.base.items():
            testcase.assertEqual(
                self.read(rel), data, f"{rel} does not match the pre-install bytes"
            )


APP_BASE = (
    "\n".join(f"line {index}" for index in range(1, 31)) + "\n"
)
APP_PATCHED = APP_BASE.replace("line 10", "line 10 changed")
DOCS_BASE = (
    "title\n"
    "intro a\n"
    "intro b\n"
    "intro c\n"
    "old body\n"
    "old body two\n"
    "tail a\n"
    "tail b\n"
    "tail c\n"
    "tail d\n"
)
DOCS_PATCHED = DOCS_BASE.replace("old body two", "new body two")
NESTED_BASE = "export const deep = 'base';\n"
NESTED_PATCHED = "export const deep = 'patched';\n"
RUN_BASE = "#!/bin/sh\necho base\n"
RUN_PATCHED = "#!/bin/sh\necho patched\n"
CRLF_BASE = b"one\r\ntwo\r\nthree\r\n"
CRLF_PATCHED = b"one\r\ntwo changed\r\nthree\r\n"
NEW_FILE = b"export const added = 1;\n"
NEW_NESTED = b"nested addition\n"


def build_fixture(root: Path, executable: bool = True) -> Fixture:
    source = root / "orca"
    source.mkdir()
    run_git(source, "init", "-q")
    run_git(source, "config", "user.email", "installer-test@example.invalid")
    run_git(source, "config", "user.name", "Installer Test")
    run_git(source, "config", "core.autocrlf", "false")

    files = {
        "src/app.ts": APP_BASE.encode(),
        "src/deep/nested/file.ts": NESTED_BASE.encode(),
        "docs/readme.md": DOCS_BASE.encode(),
        "tools/run.sh": RUN_BASE.encode(),
        "crlf.txt": CRLF_BASE,
        "unrelated/keep.txt": b"keep me\n",
    }
    for rel, data in files.items():
        path = source.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        mode = 0o755 if rel == "tools/run.sh" and executable else 0o644
        os.chmod(path, mode)

    run_git(source, "add", ".")
    run_git(source, "commit", "-qm", "base")
    base_commit = run_git(source, "rev-parse", "HEAD").decode().strip()

    bundle = root / "bundle"
    (bundle / "patches").mkdir(parents=True)
    (bundle / "changes").mkdir()
    (bundle / "examples").mkdir()

    # Apply the change in the working tree, generate the patch, and snapshot.
    changed = {
        "src/app.ts": APP_PATCHED.encode(),
        "src/deep/nested/file.ts": NESTED_PATCHED.encode(),
        "docs/readme.md": DOCS_PATCHED.encode(),
        "tools/run.sh": RUN_PATCHED.encode(),
        "crlf.txt": CRLF_PATCHED,
        "src/new.ts": NEW_FILE,
        "newdir/created/file.txt": NEW_NESTED,
    }
    for rel, data in changed.items():
        destination = source.joinpath(*rel.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    run_git(source, "add", "-N", "src/new.ts")
    run_git(source, "add", "-N", "newdir/created/file.txt")
    patch = run_git(source, "diff")
    (bundle / "patches" / "test.patch").write_bytes(patch)

    managed = [
        "src/app.ts",
        "src/deep/nested/file.ts",
        "docs/readme.md",
        "tools/run.sh",
        "crlf.txt",
        "src/new.ts",
        "newdir/created/file.txt",
    ]
    added = ["src/new.ts", "newdir/created/file.txt"]
    files_manifest = []
    for rel in managed:
        data = source.joinpath(*rel.split("/")).read_bytes()
        snapshot = bundle / "changes" / rel
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(data)
        files_manifest.append(
            {
                "upstreamPath": rel,
                "snapshotPath": f"changes/{rel}",
                "sha256": sha(data),
            }
        )

    example = bundle / "examples" / "workflow.json"
    example.write_bytes(b'{"example": true}\n')
    manifest = {
        "formatVersion": 1,
        "upstream": {
            "repository": "https://example.invalid/orca",
            "version": "test",
            "baseCommit": base_commit,
        },
        "implementationCommit": None,
        "patch": {
            "path": "patches/test.patch",
            "sha256": sha(patch),
        },
        "example": {
            "path": "examples/workflow.json",
            "sha256": sha(example.read_bytes()),
        },
        "files": files_manifest,
    }
    (bundle / "bundle-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    run_git(source, "reset", "-q")
    run_git(source, "checkout", "-q", "--", ".")
    for rel in added:
        path = source.joinpath(*rel.split("/"))
        if path.exists():
            path.unlink()
    for rel_dir in ("newdir/created", "newdir"):
        path = source / rel_dir
        if path.exists():
            try:
                path.rmdir()
            except OSError:
                pass

    fixture = Fixture(
        root=root,
        source=source,
        bundle=bundle,
        base_commit=base_commit,
        managed=managed,
        added=added,
        updated=[item for item in managed if item not in added],
    )
    for rel in files:
        fixture.base[rel] = source.joinpath(*rel.split("/")).read_bytes()
        fixture.base_modes[rel] = stat.S_IMODE(source.joinpath(*rel.split("/")).stat().st_mode)
    return fixture


def write_manifest(bundle: Path, manifest: dict) -> None:
    (bundle / "bundle-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def read_manifest(bundle: Path) -> dict:
    return json.loads((bundle / "bundle-manifest.json").read_text(encoding="utf-8"))


def find_backup_manifest(state: dict) -> Path:
    return Path(state["installation"]["backup"]["manifestPath"])


def remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
