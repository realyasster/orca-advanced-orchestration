# Orca Advanced Orchestration

Automatically coordinates tasks between agents such as Codex and Claude in Orca. Define a workflow once: dependent tasks start when their prerequisites finish, and independent tasks run in parallel.

Example: **Write code → Run tests and review in parallel → Fix if needed → Report results.**

## What does it do?

- Reduces manual agent launches and repeated status checks.
- Manages task dependencies, shared workspaces, and review decisions.
- Supports pausing, resuming, and cancelling workflows.
- Aims to reduce unnecessary coordinator calls during routine transitions; worker agents still consume tokens.

## Installation

From Windows PowerShell, without cloning this repository:

```powershell
irm https://raw.githubusercontent.com/realyasster/orca-advanced-orchestration/main/install.ps1 | iex
```

Choose **Install** in the menu. The script downloads only the versioned ZIP required for installation from GitHub Releases, verifies its SHA-256 checksum and every bundle hash, and caches it by version under `%LOCALAPPDATA%\OrcaAdvancedOrchestration`. It never downloads the full repository, Git history, tests, or development files.

Requirements: **Python 3.9+** and **Git**. If no Orca source checkout exists, the menu can clone the upstream version supported by the package. If the cloned `HEAD` differs from the package's required base commit, the tool refuses with a clear error and never runs `git reset` or `git checkout` automatically.

This repository is not a standalone application or plugin: it **modifies the Orca v1.4.246 source code**. After installation the source is patched, but the new behavior is not active until you build it:

```powershell
cd <orca-source>
pnpm install --frozen-lockfile
pnpm build
```

Menu: **Install**, **Update**, **Uninstall**, **Status and versions**, **Verify**, **Operation rehearsal**, **Change Orca source path**, **Exit**. The source path is persisted.

Non-interactive use:

```powershell
.\install.ps1 -Action install -Source C:\orca-dev
.\install.ps1 -Action update -Source C:\orca-dev
.\install.ps1 -Action update -Source C:\orca-dev -Version 1.0.0 -DryRun
.\install.ps1 -Action status -Source C:\orca-dev
.\install.ps1 -Action verify
.\install.ps1 -Action uninstall -Source C:\orca-dev
```

Without `-Version`, the latest stable GitHub Release is resolved once per action. `-DryRun` rehearses install, update, or uninstall without changing files. Under `irm | iex` the script never calls `exit` on the caller's shell.

## Update, rollback, and uninstall

- Updating to the same version is a no-op.
- No file is changed until the complete new package has been downloaded and verified.
- Local edits, a different upstream base, and package-version mismatches are checked first; incompatible bases are never reset automatically.
- Updates run under one lock with a durable journal. On failure or interruption the previously installed version is restored.
- The first pre-install original backup is preserved. Uninstall restores original files, archives files changed after installation, and never deletes the Orca source directory.
- The cached management tool supports offline uninstall.

## Publishing the package

The release ZIP contains only runtime installation files. Build it locally with:

```powershell
python scripts/build_release.py --output dist
```

This produces a ZIP versioned from `package.version` in `bundle-manifest.json` plus its `.sha256` file. `.github/workflows/release.yml` runs the tests on a `v*` tag, checks the tag against the manifest version, and uploads both assets to a GitHub Release. If no release has been published yet, the real `irm` download cannot work; use `-Version` with a pre-populated cache for offline testing.

**[Installation and usage guide](docs/USAGE.en.md)** · [Example workflow](examples/workflow.json)

[Türkçe](README.md) · [Technical design](docs/DESIGN.md) · [Test results and known limitations](docs/VALIDATION.md) · [MIT license](LICENSE)
