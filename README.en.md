# Orca Advanced Orchestration

Automatically coordinates tasks between agents such as Codex and Claude in Orca. Define a workflow once: dependent tasks start when their prerequisites finish, and independent tasks run in parallel.

Example: **Write code → Run tests and review in parallel → Fix if needed → Report results.**

## What does it do?

- Reduces manual agent launches and repeated status checks.
- Manages task dependencies, shared workspaces, and review decisions.
- Supports pausing, resuming, and cancelling workflows.
- Aims to reduce unnecessary coordinator calls during routine transitions; worker agents still consume tokens.
- Adds a persistent per-workspace **Todo** column to the left of the agent board; Todo items do not launch agents.

## Installation

From Windows PowerShell, without cloning this repository:

```powershell
irm https://raw.githubusercontent.com/realyasster/orca-advanced-orchestration/v1.1.0/install.ps1 | iex
```

Choose **Install (select components)** in the menu and toggle **Orchestrator** and **Todo** independently. The script downloads only the versioned ZIP required for installation from GitHub Releases, verifies its SHA-256 checksum and every bundle hash, and caches it by version under `%LOCALAPPDATA%\OrcaAdvancedOrchestration`. It never downloads the full repository, Git history, tests, or development files.

Requirements: **Python 3.9+** and **Git**. The Orca source checkout is located automatically; when none exists, **Install** clones the supported version into `%USERPROFILE%\orca-dev` without asking for a path. Pass `-Source` to use a different checkout. If the cloned `HEAD` differs from the package's required base commit, the tool refuses with a clear error and never runs `git reset` or `git checkout` automatically.

This repository is not a standalone application or plugin: it **modifies the Orca v1.4.246 source code**. After installation the source is patched, but the new behavior is not active until you build it:

```powershell
cd <orca-source>
pnpm install --frozen-lockfile
pnpm build
```

Menu: **Install (select components)**, **Update**, **Uninstall**, **Status and versions**, **Verify**, **Operation rehearsal**, **Change Orca source path**, **Change language**, **Exit**. The source path is persisted.

The first menu start asks for the interface language (`Dil / Language [1] Turkce [2] English`) and saves it in `config.json`; non-menu actions never prompt for it. Change it later with **Change language** or per run with `-Lang tr|en`. A persisted source path that is temporarily unavailable is kept and ignored for that run.

Non-interactive use:

```powershell
.\install.ps1 -Action install -Source C:\orca-dev
.\install.ps1 -Action update -Source C:\orca-dev
.\install.ps1 -Action update -Source C:\orca-dev -Version 1.1.0 -DryRun
.\install.ps1 -Action status -Source C:\orca-dev
.\install.ps1 -Action verify
.\install.ps1 -Action uninstall -Source C:\orca-dev
.\install.ps1 -Action install -Source C:\orca-dev -Pack todo
```

`-Pack` selects one or more comma-separated components; omitting it installs every pack. Without `-Version`, the latest stable GitHub Release is resolved once per action. `-DryRun` rehearses install, update, or uninstall without changing files. `-Lang tr|en` selects the interface language for that run. Under `irm | iex` the script never calls `exit` on the caller's shell.

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
