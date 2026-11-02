# Orca Advanced Orchestration

An independent **change bundle** adding event-driven automatic workflows to Orca's core runtime.

[Türkçe README](README.md) · [Design](docs/DESIGN.md) · [Validation](docs/VALIDATION.md) · [MIT license](LICENSE)

Define a workflow once. Orca schedules dependent agents, while the coordinator handles planning, questions, failures, review decisions, and the final report. Worker agents still consume tokens; no production token-savings percentage is claimed.

This repository contains only the orchestration changes, their tests, documentation, and an example. It does **not** contain the full Orca repository or upstream Git history. It is not a plugin or a standalone application.

## Contents

- `patches/automatic-orchestration.patch`: actual changes against Orca v1.4.246.
- `changes/`: post-change snapshots of the 77 affected source and skill-guide files, preserving upstream paths. Existing files include surrounding upstream code; the patch identifies the changed lines.
- `examples/workflow.json`: implementation followed by parallel testing and review.
- `bundle-manifest.json`: exact base, implementation reference, and SHA-256 hashes.
- `scripts/verify_bundle.py`: bundle integrity verification.

Capabilities include sequential and parallel dependencies, two workers by default, versioned workflow updates, durable scheduling events, interrupted-launch recovery, workspace coordination, review gates, bounded correction rounds, pause/resume/cancel, and CLI/RPC integration.

## Apply to Orca

The supported base is [stablyai/orca](https://github.com/stablyai/orca) v1.4.246, commit `55ccff19ad4cd8ba28b6f3d2be798c1e626a2c2c`.

```sh
git clone https://github.com/realyasster/orca-advanced-orchestration.git
cd orca-advanced-orchestration
python scripts/verify_bundle.py
cd ..
git clone --branch v1.4.246 --depth 1 https://github.com/stablyai/orca.git orca-dev
cd orca-dev
git rev-parse HEAD
git switch -c feature/automatic-orchestration
git apply --check ../orca-advanced-orchestration/patches/automatic-orchestration.patch
git apply ../orca-advanced-orchestration/patches/automatic-orchestration.patch
```

Confirm the checkout matches the base commit above. These paths assume sibling clones. Apply the patch once; copying the snapshots separately is unnecessary. Compatibility with other Orca versions has not been verified.

Install dependencies and start the **patched Orca checkout**, not this bundle:

```sh
pnpm install --frozen-lockfile
pnpm dev --worktree-profile
```

Use Node.js 24, Orca's pinned pnpm/Bun versions, and the native prerequisites in its `.github/CONTRIBUTING.md`. No installer or packaged Orca release is provided here.

Workflow creation and controls are documented in [the main README](README.md). Use `node config/scripts/orca-dev.mjs` from the patched checkout to target its development runtime; bare `orca` may target an installed build without these changes.

## Verification and limitations

**48 focused tests passed across 7 files.** Changed-code lint reports two `max-lines` errors. Full CI, packaging, and a live multi-agent end-to-end run were not verified. Tests use controlled worker hosts; they do not measure production token usage. See [validation details](docs/VALIDATION.md).

Based on Orca by Stably / Lovecast Inc.; upstream MIT copyright and license notices are retained. Independently maintained, with no claim of upstream endorsement.
