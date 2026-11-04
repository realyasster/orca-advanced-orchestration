# Orca Advanced Orchestration

An independent **change bundle** adding event-driven automatic workflows to Orca's core runtime.

[Türkçe README](../README.md) · [Design](../docs/DESIGN.md) · [Validation](../docs/VALIDATION.md) · [MIT license](../LICENSE)

Define a workflow once. Orca schedules dependent agents, while the coordinator handles planning, questions, failures, review decisions, and the final report. Worker agents still consume tokens; no production token-savings percentage is claimed.

This repository contains only the orchestration changes, their tests, documentation, and an example. It does **not** contain the full Orca repository or upstream Git history. It is not a plugin or a standalone application.

## Contents

- [`scripts/manage_installation.py`](../scripts/manage_installation.py): backup-aware install/status/uninstall tool for a source checkout.
- [`install.ps1`](../install.ps1): interactive PowerShell installation menu for Windows.
- [`scripts/orca_install/`](../scripts/orca_install/): bundle verification, locking, journal, backup, and restore modules.
- `patches/automatic-orchestration.patch`: actual changes against Orca v1.4.246.
- `changes/`: post-change snapshots of the 133 affected source and skill-guide files, preserving upstream paths. Existing files include surrounding upstream code; the patch identifies the changed lines.
- `examples/workflow.json`: implementation followed by parallel testing and review.
- `bundle-manifest.json`: exact base, implementation reference, pack definitions, and SHA-256 hashes.
- `scripts/verify_bundle.py`: bundle integrity verification.
- [`tests/`](../tests/): installer tests using only the Python standard library.

Capabilities include sequential and parallel dependencies, two workers by default, versioned workflow updates, durable scheduling events, interrupted-launch recovery, workspace coordination, review gates, bounded correction rounds, pause/resume/cancel, and CLI/RPC integration.

## Apply to Orca

The supported base is [stablyai/orca](https://github.com/stablyai/orca) v1.4.246, commit `55ccff19ad4cd8ba28b6f3d2be798c1e626a2c2c`.

The automated tool manages **only a source checkout whose `HEAD` is the supported base commit**. It does not change an installed or packaged Orca application. If the checkout `HEAD` differs, it refuses before touching any source file.

### Automated installation (recommended)

Python 3.9+ and Git are required; no third-party Python packages are needed.

```sh
git clone https://github.com/realyasster/orca-advanced-orchestration.git
git -c core.autocrlf=false clone --branch v1.4.246 --depth 1 https://github.com/stablyai/orca.git orca-dev
cd orca-advanced-orchestration
python scripts/manage_installation.py install --source ../orca-dev
```

This assumes sibling clones. `--source` must point at the Git root of the checkout. On Windows, `core.autocrlf=false` keeps the LF line endings the patch expects.

### PowerShell menu (Windows)

Once an `orca-dev` checkout is ready, open the menu with one command (the script downloads the bundle temporarily when it is not present locally):

```powershell
cd orca-advanced-orchestration
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

Choose an action:

```text
  1) Install (choose components)
  2) Status
  3) Uninstall
  4) Install dry-run (choose components)
  5) Uninstall dry-run
  6) Verify bundle
  7) Change Orca source path
  0) Exit
```

In the menu, `3) Uninstall` asks for confirmation before starting; if declined, nothing changes. Direct `-Action uninstall` does not prompt. If `7) Change Orca source path` is cancelled, the previous source path is kept.

`install.ps1` only wraps the existing Python tool. It does **not** clone the Orca checkout. When the bundle repository is absent locally, it downloads a temporary archive from `-BundleUrl` (the GitHub `main` archive by default). Without `-Source`, it looks for `..\orca-dev` first and then asks for a path.

Run a single action directly:

```powershell
.\install.ps1 -Action install -Source ..\orca-dev
.\install.ps1 -Action install -Source ..\orca-dev -Pack todo
.\install.ps1 -Action install -Source ..\orca-dev -Pack orchestration,todo -DryRun
.\install.ps1 -Action status -Source ..\orca-dev
.\install.ps1 -Action uninstall -Source ..\orca-dev
.\install.ps1 -Action verify
```

`-NoPause` skips the wait after an action for automation. Use `-RepoRoot` when the repository root cannot be detected automatically. A direct `-Action install` without `-Pack` installs every component without prompting; the menu asks for components, and `-NoPause` or redirected input also skips the prompt in favor of all packs.

`irm ... | iex` opens the same menu. If the bundle repository is not present locally, the script downloads a temporary archive and removes it afterwards:

```powershell
irm https://raw.githubusercontent.com/realyasster/orca-advanced-orchestration/b9f7e62f3ea89ba51e4e102817c16920b473a7fe/install.ps1 | iex
```

`iex` executes downloaded code directly; inspect the URL and the script first. The bootstrap resolves `-BundleRef` (default `v1.4.246-todo.1`) to an immutable GitHub commit SHA, downloads that commit's archive, and verifies the SHA-256 of `bundle-manifest.json` plus the **bootstrap script hash list** in that manifest. Use `-BundleRef`, `-BundleUrl`, `-BundleManifestSha256`, and optionally `-BundleArchiveSha256` for a different version, a local archive, or full ZIP verification. The default requires the release tag to exist; `-BundleRef main` is available as a temporary override.

### Component selection

The bundle contains two independent components:

| Pack | Contents |
| --- | --- |
| `orchestration` | Event-driven automatic orchestration, CLI/RPC, database, and decision gates |
| `todo` | Persistent Todo column at the left of the agent board |

The install menu shows a checkbox-style list: press a number to toggle, **Enter** to install, `A` for all, `N` for none, `Q` to cancel. Both are selected by default.

Select directly:

```sh
python scripts/manage_installation.py install --source ../orca-dev --pack todo
python scripts/manage_installation.py install --source ../orca-dev --pack orchestration
python scripts/manage_installation.py install --source ../orca-dev --pack todo,orchestration
```

Omitting `--pack` installs every component. The selection is written to the installation record and shown by `status`. To change a selection, uninstall first and install again.

Preview actions without changing anything:

```sh
python scripts/manage_installation.py install --source ../orca-dev --pack todo --dry-run
```

During installation the tool:

1. Verifies the patch, example, and all 133 file SHA-256 values in `bundle-manifest.json`, 135 bundle files in total.
2. Checks the Git checkout, the supported base commit, every managed path, and symlink/junction safety.
3. Applies the patch to temporary copies of the affected local files, preserving compatible local edits. If the patch does not apply exactly, it stops without changing the target.
4. Stores the **raw bytes and permissions** of existing managed files under the checkout's Git data directory, verifies the backup hashes, and writes a durable JSON journal.
5. Replaces each file atomically, records progress, and verifies every resulting hash.
6. On a write failure, restores changed files from the first backup. If rollback cannot complete, it does not claim success and marks the installation `recovery_required`.

The backup is checkout-specific:

```text
<git-dir>/orca-advanced-orchestration/<installation-id>/backup
```

Find `<git-dir>` with `git -C ../orca-dev rev-parse --absolute-git-dir`. For a linked worktree, the per-worktree Git directory returned by Git is used, so it never mixes with the main checkout's backup.

The tool does not build, launch, migrate a database, or replace an installed binary. After installing (or after restoring sources), build and run the development app separately.

### Status and repeat installation

```sh
python scripts/manage_installation.py status --source ../orca-dev
```

`status` is read-only. It shows the installation id, package, backup path, recovery archives, files changed or missing since installation, and any pending interruption. It creates no files, backups, locks, or journal entries.

Re-running `install` for the same package succeeds without changes and **never overwrites the first backup**. Files edited locally after installation are not silently reverted. If a different package version is installed, uninstall it first.

### Uninstall and recovery archive

```sh
python scripts/manage_installation.py uninstall --source ../orca-dev --dry-run
python scripts/manage_installation.py uninstall --source ../orca-dev
```

`uninstall` uses the list and backup recorded at installation time, **not the current bundle manifest**. It still works if the bundle is later updated or deleted. It:

1. Verifies the target checkout identity, recorded paths, and every backup hash. A missing or corrupt backup means no target file is touched.
2. Archives the current bytes of files changed since installation. Original files that went missing are recorded with a "missing" entry in the archive manifest.
3. Re-verifies the archive hashes before restoring anything.
4. Restores files that existed before installation from the first backup, byte-for-byte and with their permissions.
5. Removes files added by the installation; new files edited after installation are archived first.
6. Removes only installation-created directories that are still empty. Directories containing user content are kept.
7. Verifies result hashes and permissions and records `uninstalled`.

Recovery archive location:

```text
<git-dir>/orca-advanced-orchestration/<installation-id>/recovery/<archive-id>/
```

The archive's `manifest.json` records why each file was archived (`modified-after-install` or `missing-before-uninstall`), its hash, and its archive path. The first backup and recovery archives are retained after uninstall; their paths appear in command output and `status`.

A second `uninstall` is a safe no-op. A later install creates a new installation id and a new backup; older backups are retained.

### Interruptions, locking, and safety

Recorded states: `installing`, `installed`, `uninstalling`, `uninstalled`, `recovery_required`.

- If an operation is interrupted, the next `install`/`uninstall` reconciles the journal first and does not start a new mutation in the same invocation. An interrupted install rolls back from backup and asks you to re-run install; an interrupted uninstall resumes and completes.
- Content that matches neither the original nor the recorded installed version is archived before restore.
- In `recovery_required`, the tool refuses to continue automatically. Inspect the recorded paths and files, repair them, then proceed deliberately.
- A lock prevents concurrent operations on the same checkout. A stale lock is reclaimed only when its owner is provably not running; uncertain process liveness never breaks the lock automatically.
- Manifest, record, and target paths that escape the checkout (`..`, absolute paths, drive syntax) or traverse symlinks/junctions are rejected.

`--dry-run` creates no files, backups, locks, or journal entries. `status` is always read-only.

### Manual installation (alternative)

```sh
cd orca-dev
git rev-parse HEAD
git switch -c feature/automatic-orchestration
git apply --check ../orca-advanced-orchestration/patches/automatic-orchestration.patch
git apply ../orca-advanced-orchestration/patches/automatic-orchestration.patch
```

Confirm the checkout matches the base commit above. Manual application provides no backup, journal, status tracking, or automatic restore; use your Git branch to revert. Compatibility with other Orca versions has not been verified.

### Build after installation

Installation only changes source files; build the patched Orca checkout before the changes can run:

```sh
cd ../orca-dev
pnpm install --frozen-lockfile
pnpm build
```

`pnpm dev --worktree-profile` builds the packages needed for development. Use `pnpm build` for a full desktop and native build; the new automation behavior is not active until that build completes.

## Run the development build

Run these commands in the **patched Orca source checkout**, not this bundle. Use Node.js 24, Orca's pinned pnpm/Bun versions, and the native prerequisites in its `.github/CONTRIBUTING.md`.

```sh
pnpm install --frozen-lockfile
pnpm dev --worktree-profile
```

Use the development profile rather than modifying a production installation. This repository does not publish an installer or a packaged Orca release.

## Workflow creation and controls

With the development app running, use Orca's managed coordinator terminal:

```sh
node config/scripts/orca-dev.mjs orchestration run-create --objective "Implement, test, and review a change" --mode automatic --max-parallel 2 --json
node config/scripts/orca-dev.mjs orchestration workflow-apply --run "<run_id>" --workflow-file ../orca-advanced-orchestration/examples/workflow.json --expected-version 0 --json
node config/scripts/orca-dev.mjs orchestration run-start --id "<run_id>" --json
```

Adjust the example task instructions for your work. Codex and Claude must be installed and enabled inside Orca. `workspaceFrom` passes the implementation workspace to later workers. Change the workflow path for your terminal's working directory if needed.

Controls are documented in [the usage guide](USAGE.md#kontroller). Use `node config/scripts/orca-dev.mjs` from the patched checkout to target its development runtime; bare `orca` may target an installed build without these changes.

## Board Todo column

The **Todo** column at the far left of the agent board holds manual work items independent of agents. Choose **Add**, type one line, and pick a workspace; the active workspace is the default. Enter saves and Escape cancels. Click a card's text to edit it in place and use the checkbox to complete it. Completed items move into a collapsed **Completed** section at the bottom of the same column and can be reopened. Deleting from the card menu shows a short-lived **Undo** action. Each workspace has its own persistent list; items never launch agents or move into Done.

## Verification and limitations

**178 focused Orca tests across 14 files** and **48 automatic-orchestration regression tests across 7 files** passed, with no lint or TypeScript errors in the changed files. The installer has **55 passing Python tests** covering clean and interrupted installs, status, uninstall, recovery archives, CRLF, permissions, backup validation, lock races, path traversal, symlinks/junctions, linked worktrees, the PowerShell menu, and applying the real 133-file patch to a base tree.

Full CI, packaging, and a live multi-agent end-to-end run were not verified. Tests use controlled worker hosts; they do not measure production token usage. The real-patch fixture test uses `ORCA_SOURCE_CHECKOUT` (or a local `orca-source/` directory) and is skipped when absent. A real install/status/uninstall roundtrip was run on a temporary worktree at the base commit with `core.autocrlf=false`.

```sh
python scripts/verify_bundle.py
python -m unittest discover -s tests -v
```

See [validation details](../docs/VALIDATION.md).

Based on Orca by Stably / Lovecast Inc.; upstream MIT copyright and license notices are retained. Independently maintained, with no claim of upstream endorsement.
