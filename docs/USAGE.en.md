# Orca Advanced Orchestration usage guide

This package applies automatic task orchestration changes to the Orca v1.4.246 source code. It is not a standalone application or plugin; the source checkout must be built after installation.

[Türkçe](USAGE.md) · [README](../README.en.md) · [Design](DESIGN.md) · [Validation](VALIDATION.md)

## Quick start

From any working directory in Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/realyasster/orca-advanced-orchestration/v1.1.1/install.ps1 | iex
```

Choose **Install** in the menu. The script:

1. Checks Python 3.9+ and Git.
2. Resolves the latest stable GitHub Release once (or uses `-Version`).
3. Downloads the versioned ZIP and `.sha256` containing only installation files.
4. Verifies the ZIP SHA-256, then every one of the 133 file hashes in `bundle-manifest.json` (135 package files including the patch and example).
5. Caches the package by version under `%LOCALAPPDATA%\OrcaAdvancedOrchestration\packages\<version>\`.
6. Resolves an Orca source checkout; offers to clone the supported upstream version when missing.
7. Compares the target `HEAD` with the package's base commit.
8. Creates a verified backup and applies the changes.

It never downloads the full repository, Git history, tests, or development files.

### Requirements

- Windows PowerShell 5.1 or PowerShell 7.
- Python 3.9+ (`py -3`, `python`, or `python3`).
- Git.
- Node.js 24 and Orca's pinned pnpm version for the build.

### Orca source checkout

Pass an existing checkout with `-Source`. Otherwise the tool locates one itself, in this order:

1. The persisted source path in `config.json`.
2. `orca-dev` / `orca` beside the local package directory, in the current directory, and in its parent.
3. Common development locations under `%USERPROFILE%` (`orca-dev`, `dev\orca`, `projects\orca`, `source\repos\orca`, ...) and drive roots such as `C:\orca` and `C:\dev\orca`.
4. A Git checkout one level below `%USERPROFILE%` or a known development root whose `package.json` name is `orca` or whose `origin` remote is `stablyai/orca`.

When nothing is found, **Install** clones the supported version into `%USERPROFILE%\orca-dev` without asking for a path:

```powershell
git -c core.autocrlf=false clone --branch v1.4.246 --depth 1 https://github.com/stablyai/orca.git <path>
```

A failed clone removes the partial destination. If the cloned `HEAD` is not `upstream.baseCommit`, the tool refuses with a clear error; it never runs `git reset` or `git checkout` automatically.

- **An explicit `-Source` is authoritative**: an invalid path fails immediately; discovery and auto-clone are not attempted.
- **A saved path that is temporarily unavailable** (`config.json`) is kept; it is ignored for that run and discovery continues.
- **Multiple candidates** prompt for a numbered choice in the interactive menu; non-interactive runs use the first one and print a warning. The selected checkout's `HEAD` is compared with the package base commit and a warning is printed on mismatch.
- **Update** and **Uninstall** never clone and never prompt for a path; without a source they fail with a clear `-Source` hint. **Status** reports package and cache information when no source exists.

## Menu

```text
  1) Install (select components)
  2) Update
  3) Uninstall
  4) Status and versions
  5) Verify
  6) Operation rehearsal (dry-run)
  7) Change Orca source path
  8) Change language (Turkce/English)
  0) Exit
```

- **Install (select components)**: downloads/verifies the package, then toggles **Orchestrator** and **Todo** independently before applying only the selected file group.
- **Update**: compares the installed and target versions; same version is a no-op. The new package is fully downloaded and verified, preflight checks run, and the operation executes under one lock.
- **Uninstall**: restores original files, archives files changed after installation, and never deletes the Orca source directory. Asks for confirmation.
- **Status and versions**: shows installation state, package version, backups, local changes, cached versions, and the latest stable version when reachable.
- **Verify**: verifies package hashes and, when present, the installation record and backup.
- **Operation rehearsal**: runs install, update, or uninstall with `--dry-run`; no file changes.
- **Change Orca source path**: validates and persists the new path. Cancellation keeps the previous path.
- **Change language**: switches the interface between Turkce and English and saves the choice in `config.json`. The first menu start asks for the language; `-Lang tr|en` applies to that run only.

Under `irm | iex` the script never calls `exit` on the caller's shell. With `-File` it returns an exit code.

### Component (pack) selection

The manifest defines two independent packs:

- `orchestration`: automatic orchestration, CLI/RPC, migration, and decision gates (81 files).
- `todo`: a persistent Todo column on the left of the agent board (52 files).

In the install menu, press a number to toggle a component. Enter installs the selected set; `A` selects all and `N` clears all. Non-interactive installs without `-Pack` install every pack. To change an installed selection, uninstall first and install again with the new selection.

```powershell
.\install.ps1 -Action install -Source C:\orca-dev -Pack todo
.\install.ps1 -Action install -Source C:\orca-dev -Pack orchestration,todo
```

`update` preserves the installed pack selection. Todo items never launch agents and are stored per workspace.

## Non-interactive use

```powershell
.\install.ps1 -Action install -Source C:\orca-dev
.\install.ps1 -Action install -Source C:\orca-dev -Version 1.1.1 -DryRun
.\install.ps1 -Action install -Source C:\orca-dev -Pack todo
.\install.ps1 -Action update -Source C:\orca-dev
.\install.ps1 -Action update -Source C:\orca-dev -Version 1.1.1 -DryRun
.\install.ps1 -Action status -Source C:\orca-dev
.\install.ps1 -Action verify
.\install.ps1 -Action uninstall -Source C:\orca-dev
```

- Without `-Version`, the latest stable GitHub Release is resolved once per action.
- Without `-Source`, the persisted path and known locations are tried; non-interactive mode fails clearly if none exists.
- `-RepoRoot` selects a local package directory and skips downloads.
- `-Lang tr|en` selects the interface language without changing the saved language setting.
- `-NoPause` disables the end-of-action wait.
- `-DryRun` is meaningful only for install, update, and uninstall.

To run only from a local package directory:

```powershell
cd orca-advanced-orchestration
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -RepoRoot . -Action install -Source ..\orca-dev
```

Local mode reads the version from `bundle-manifest.json`; `-Version` cannot be used there.

## Cache, offline use, and integrity

```text
%LOCALAPPDATA%\OrcaAdvancedOrchestration\
  config.json
  packages\<version>\
    .verified
    bundle-manifest.json
    install.ps1
    scripts\...
    changes\...
  downloads\
```

- The downloaded ZIP is compared with the SHA-256 asset before extraction.
- Archive paths that escape the destination (`..`, rooted paths, drive syntax) are rejected.
- `.verified` is written only after bundle hashes pass.
- A cached version is reused; the version is resolved once per action.
- Uninstall works without network access through the cached management tool. If the cache is empty and the installed version is unknown, it fails clearly.

## Build after installation

Installation only changes source files. The tool does not build, launch the app, migrate a database, or replace an installed binary. Patched source and a ready-to-use application are separate states.

```powershell
cd <orca-source>
pnpm install --frozen-lockfile
pnpm build
```

For development:

```powershell
pnpm dev --worktree-profile
```

After install/update the menu prints these commands and, in interactive mode, offers to run them.

## Direct Python tool

The PowerShell script wraps the Python tool. The same operations are available directly:

```sh
python scripts/manage_installation.py install --source ../orca-dev --dry-run
python scripts/manage_installation.py install --source ../orca-dev
python scripts/manage_installation.py update --source ../orca-dev --dry-run
python scripts/manage_installation.py update --source ../orca-dev
python scripts/manage_installation.py status --source ../orca-dev
python scripts/manage_installation.py status --source ../orca-dev --json
python scripts/manage_installation.py verify --source ../orca-dev
python scripts/manage_installation.py uninstall --source ../orca-dev --dry-run
python scripts/manage_installation.py uninstall --source ../orca-dev
```

There is no `--bundle` CLI flag; the tool uses its own package root (the directory containing `bundle-manifest.json`). To use a cached version, run `scripts/manage_installation.py` from that version's directory. Uninstall does not need the current bundle manifest.

## Installation flow

1. Verifies the manifest, patch, example, and all 133 file SHA-256 values.
2. Checks the Git checkout, base commit, managed paths, and symlink/junction safety.
3. Applies the patch to temporary copies of affected files. Compatible local edits are preserved; a patch that does not apply stops without changing the target.
4. Stores raw bytes and permissions of existing managed files under the checkout's Git data directory, verifies hashes, and writes a durable JSON journal.
5. Replaces files atomically, records progress, and verifies resulting hashes.
6. On a write failure, restores changed files from the first backup. If rollback cannot complete, marks `recovery_required` and never claims success.

Checkout-specific backup location:

```text
<git-dir>/orca-advanced-orchestration/<installation-id>/backup
```

For a linked worktree, the per-worktree Git directory returned by Git is used.

## Update flow

- With no active installation or `uninstalled` state, update is refused; use install.
- Identical package fingerprint is a no-op; no file or journal is written.
- The same version with different content is rejected; publish a new version instead.
- Files modified or missing since installation block the update before any write.
- The installed and new package must target the same upstream base. Different bases or a mismatched checkout `HEAD` are never reset automatically.
- Added and removed managed paths are supported. A newly managed path that already exists is captured as an original.
- Before touching targets, the previous installed bytes are written to a verified rollback snapshot.
- One `installation.lock` and a durable journal are used. Failure or interruption restores the previous installed version; unexpected post-crash content is archived first.
- A successful update creates a cumulative original backup while preserving the first pre-install backup directory.

During an update the journal may briefly show `updating`. The next command reconciles it first and asks you to re-run the command.

## Status and verification

`status` is read-only. It shows the installation id, package version, backup, recovery archives, files changed or missing since installation, and any pending interruption. `--json` emits machine-readable output.

`verify` checks package hashes and the installation record: installed file hashes, the backup manifest, and backup bytes. It does not continue automatically in `recovery_required`.

## Uninstall and recovery archive

`uninstall` uses the list and original backup recorded at installation time, not the current manifest. It still works if the package is updated or deleted later.

1. Verifies checkout identity, recorded paths, and every backup hash.
2. Archives files changed after installation; records originals that went missing before uninstall as missing entries.
3. Re-verifies the archive before touching targets.
4. Restores original bytes and permissions.
5. Removes files added by installation, archiving post-install edits first.
6. Removes only installation-created directories that are still empty.
7. Verifies result hashes and records `uninstalled`.

Recovery archive:

```text
<git-dir>/orca-advanced-orchestration/<installation-id>/recovery/<archive-id>/
```

`manifest.json` records why each file was archived, its hash, and its archive path. The first backup and archives are retained after uninstall. A second uninstall is a safe no-op. The Orca source directory is never deleted.

## Interruptions, locking, and safety

Recorded states: `installing`, `installed`, `updating`, `uninstalling`, `uninstalled`, `recovery_required`.

- An interrupted operation is reconciled by the next command; no new mutation starts in that same invocation.
- An interrupted install rolls back to originals; an interrupted update restores the previous installed version; an interrupted uninstall resumes.
- `recovery_required` refuses automatic continuation; inspect the journal path and files.
- A lock prevents concurrent operations on the same checkout. A stale lock is reclaimed only when its owner is provably not running.
- Manifest, record, and target paths that escape the checkout or traverse symlinks/junctions are rejected.
- `--dry-run` creates no files, backups, locks, or journal entries; `status` is always read-only.

## Building and publishing the release package

Local build:

```powershell
python scripts/build_release.py --output dist
```

Outputs:

```text
dist/orca-advanced-orchestration-1.1.1.zip
dist/orca-advanced-orchestration-1.1.1.zip.sha256
```

The archive contains only `install.ps1`, `bundle-manifest.json`, `LICENSE`, the management Python modules, the patch, the example, and the 133 change snapshots. Tests, `orca-source/`, `.git`, README, and development files are excluded. The ZIP is deterministic.

The version comes from `package.version` in `bundle-manifest.json`. Do not publish the same tag without bumping it.

GitHub Actions (`.github/workflows/release.yml`):

- Runs on a `v*` tag or manually.
- Runs bundle verification and the Python tests.
- Checks the tag version against `package.version`.
- Builds the ZIP and `.sha256`, uploads a workflow artifact.
- On a tag, creates or updates a GitHub Release.

If no release has been published yet, the real `irm` download cannot work. Use `-Version` with a pre-populated cache for offline validation.

## Manual installation

```sh
cd orca-dev
git rev-parse HEAD
git switch -c feature/automatic-orchestration
git apply --check ../orca-advanced-orchestration/patches/automatic-orchestration.patch
git apply ../orca-advanced-orchestration/patches/automatic-orchestration.patch
```

The `HEAD` must equal the base commit. Manual application provides no backup, journal, status tracking, or automatic restore.

## Limitations

- The tool does not build or launch Orca or modify an installed package.
- Compatibility with other Orca versions is not verified; different upstream bases are never switched automatically.
- Update is refused when managed files have local changes after installation. Revert them or uninstall and reinstall.
- PowerShell behavior on macOS/Linux is not validated as thoroughly as on Windows.

## License and source

Based on Orca v1.4.246. Bundled Orca sources and adaptations are covered by the [MIT license](../LICENSE); upstream copyright notices are retained. This repository claims no affiliation with or endorsement by the upstream Orca project.
