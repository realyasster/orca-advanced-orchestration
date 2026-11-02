"""Small Git wrappers used by the installer.

Git is the only external program required. The environment sanitation below
avoids inheriting a malformed ``GIT_CONFIG_COUNT`` (a known hazard in some
agent shells) while leaving valid Git configuration untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import subprocess

from .errors import CheckoutError, InstallationError
from .paths import same_path


@dataclass(frozen=True)
class Checkout:
    root: Path
    git_dir: Path
    head: str


def _git_env() -> dict:
    env = os.environ.copy()
    raw_count = env.get("GIT_CONFIG_COUNT")
    try:
        count = int(raw_count) if raw_count is not None else None
    except ValueError:
        count = -1
    if count is not None:
        malformed = count < 0
        if not malformed:
            for index in range(count):
                if f"GIT_CONFIG_KEY_{index}" not in env or f"GIT_CONFIG_VALUE_{index}" not in env:
                    malformed = True
                    break
        if malformed:
            for key in list(env):
                if re.fullmatch(r"GIT_CONFIG_(COUNT|KEY_\d+|VALUE_\d+)", key):
                    env.pop(key, None)
    return env


def run_git(args, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    command = ["git", *args]
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_git_env(),
            timeout=180,
        )
    except FileNotFoundError as exc:
        raise CheckoutError("Git is required but was not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise InstallationError(f"Git command timed out: {' '.join(command)}") from exc
    if check and result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()
        raise CheckoutError(
            f"Git command failed ({' '.join(command)}): {stderr or 'no error output'}"
        )
    return result


def _git_text(args, cwd: Path) -> str:
    result = run_git(args, cwd)
    return result.stdout.decode("utf-8", "replace").strip()


def resolve_checkout(source: Path | str) -> Checkout:
    """Resolve and validate an Orca source checkout root."""

    try:
        candidate = Path(source).expanduser()
    except TypeError as exc:
        raise CheckoutError(f"Invalid source path: {source!r}") from exc
    if not candidate.exists():
        raise CheckoutError(f"Source checkout does not exist: {candidate}")
    if not candidate.is_dir():
        raise CheckoutError(f"Source is not a directory: {candidate}")
    candidate = candidate.resolve()

    inside = run_git(["rev-parse", "--is-inside-work-tree"], cwd=candidate).stdout
    if inside.decode("utf-8", "replace").strip() != "true":
        raise CheckoutError(f"Source is not a Git working tree: {candidate}")
    top = Path(_git_text(["rev-parse", "--show-toplevel"], cwd=candidate)).resolve()
    if not same_path(top, candidate):
        raise CheckoutError(
            f"--source must be the checkout root. Got '{candidate}', but Git root is '{top}'."
        )
    git_dir = Path(_git_text(["rev-parse", "--absolute-git-dir"], cwd=candidate)).resolve()
    if not git_dir.is_dir():
        raise CheckoutError(f"Git data directory was not found: {git_dir}")
    head = _git_text(["rev-parse", "HEAD"], cwd=candidate)
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", head):
        raise CheckoutError(f"Could not resolve the current commit in {candidate}")
    return Checkout(root=candidate, git_dir=git_dir, head=head.lower())


def apply_patch(patch_path: Path, cwd: Path) -> None:
    """Apply a patch inside a scratch working tree.

    The scratch tree is intentionally not a Git repository. Pinning autocrlf
    off keeps the applied bytes predictable on Windows too.
    """

    args = [
        "-c",
        "core.autocrlf=false",
        "-c",
        "core.safecrlf=false",
        "apply",
        "--whitespace=nowarn",
        str(patch_path),
    ]
    try:
        run_git(args, cwd=cwd)
    except CheckoutError as exc:
        raise InstallationError(
            "The bundle patch could not be applied to the current source files. "
            "No target file was changed. Resolve conflicting local edits or restore "
            f"the supported base tree, then retry. Git said: {exc}"
        ) from exc
