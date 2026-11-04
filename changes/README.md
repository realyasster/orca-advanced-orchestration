# Orca Advanced Orchestration

Event-driven task workflows for Orca: define the work once, let the runtime launch dependent agents, and involve the coordinator when a decision is needed.

[Türkçe](README.tr.md) · [Upstream Orca README](README.upstream.md) · [License](LICENSE)

This is an independent development repository based on [stablyai/orca](https://github.com/stablyai/orca), version **1.4.248** (base commit `965978bc`). It extends Orca's core runtime; it is **not a plugin** and is not an official Orca release.

## Why this exists

An agent coordinator should not have to keep checking whether another agent has finished, or spend a model turn launching each predictable next step. This implementation moves dependency scheduling into Orca itself.

For example, describe a workflow in your coordinator chat:

> Have Codex implement the change. When it finishes, run tests and a Claude review in parallel. Ask for a decision if something fails or the review requests changes, then report the outcome.

The coordinator creates an automatic Run and its task graph, starts it, and ends its turn. The runtime advances ready tasks from completion events. Questions, failures, review gates, and the final report still involve the coordinator.

Worker agents continue to consume tokens while doing their work. The goal is to remove unnecessary **coordinator** turns during waiting and ordinary task transitions, not to make agent execution free.

## Implemented capabilities

- Opt-in automatic Runs alongside existing manually coordinated Runs.
- Sequential dependencies and parallel branches that join before a later task.
- Two concurrent workers per Run by default; configurable in the workflow.
- Durable workflow updates with version checks; started tasks cannot be silently rewritten.
- Persistent scheduling events, interrupted-launch reconciliation, and duplicate-completion handling.
- Read/write workspace scheduling and dependency output handoffs.
- Review decision gates and correction tasks capped at two rounds.
- Pause, resume, and cancellation through the existing guarded worker-stop lifecycle.
- Automatic execution metadata in existing task and agent projections.
- Updated CLI commands, RPC contracts, database migration, and orchestration skill guidance.

The main implementation lives in [the runtime executor](src/main/runtime/orchestration/automatic-run/automatic-run-executor.ts), [workflow storage](src/main/runtime/orchestration/db/automatic-runs/), and [the workflow schema](src/shared/orchestration-workflow.ts).

## Development status

This is a source-level development implementation. No packaged release or installer is provided here, and publishing this repository does not install the feature into an existing Orca application.

Inherited GitHub Actions are disabled in this fork until its CI and release workflows are configured for independent use.

Verification performed for this publication:

| Check                                                                  | Result                                                                                                                             |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Focused automatic-run, migration, workflow, host, and CLI tests        | **48 passed across 7 files**                                                                                                       |
| Changed-code lint                                                      | Two `max-lines` errors remain in `src/cli/specs/orchestration.ts` and `src/main/runtime/runtime-agent-orchestration-projection.ts` |
| Full application build, full CI, and a live multi-agent end-to-end run | Not verified as part of this publication                                                                                           |

The test suite checks scheduling and coordinator notifications with controlled worker hosts; it is not a measured production token-savings benchmark. Review correction behavior, including re-running every relevant verification branch, should be validated against the intended workflow before relying on it for unattended work.

## Run from source

Use **Node.js 24**, the pnpm version pinned in `package.json` (12.14.0), and the Bun version pinned in `config/.bun-version` (1.4.4). Native modules also require the platform tools described in [the upstream contributing guide](.github/CONTRIBUTING.md#local-setup).

```sh
git clone https://github.com/realyasster/orca-advanced-orchestration.git
cd orca-advanced-orchestration
pnpm install --frozen-lockfile
pnpm dev --worktree-profile
```

Use a development profile for testing. Full builds also require the mobile workspace dependencies:

```sh
pnpm -C mobile install --frozen-lockfile
```

For development CLI calls, run `node config/scripts/orca-dev.mjs` from this checkout. Bare `orca` can target an installed production build that does not include these commands. See [the contributing guide](.github/CONTRIBUTING.md#dev-profiles-and-parallel-instances) for profile and CLI routing details.

## Create an automatic workflow

With the development app running, execute these commands from the coordinator's Orca-managed terminal. Replace `<run_id>` with the ID returned by the first command.

```sh
node config/scripts/orca-dev.mjs orchestration run-create --objective "Implement, test, and review a change" --mode automatic --max-parallel 2 --json
node config/scripts/orca-dev.mjs orchestration workflow-apply --run "<run_id>" --workflow-file examples/automatic-orchestration/workflow.json --expected-version 0 --json
node config/scripts/orca-dev.mjs orchestration run-start --id "<run_id>" --json
```

[The example workflow](examples/automatic-orchestration/workflow.json) launches an implementation task followed by parallel testing and review:

```text
implement (Codex, write)
    ├── test   (Codex, read)
    └── review (Claude, read; decision gate)
```

Edit its task instructions for your actual project before starting it. Codex and Claude must be installed and enabled in Orca. `workspaceFrom` reuses the implementation task's resolved workspace; `dependsOn` controls execution order.

The initial workflow version is `0`; a successful apply increments it. Later updates must provide the current version and preserve started tasks. Do not manually dispatch the automatic tasks or poll to drive their progress.

## Controls and decisions

```sh
node config/scripts/orca-dev.mjs orchestration run-show --id "<run_id>" --json
node config/scripts/orca-dev.mjs orchestration task-list --run "<run_id>" --json
node config/scripts/orca-dev.mjs orchestration run-pause --id "<run_id>" --json
node config/scripts/orca-dev.mjs orchestration run-resume --id "<run_id>" --json
node config/scripts/orca-dev.mjs orchestration run-cancel --id "<run_id>" --json
```

Pause prevents new launches while existing workers continue. Cancellation requests guarded stops; an unconfirmed stop remains visible rather than being reported as a completed cancellation. Silence or an idle terminal is not proof that a task succeeded.

When a question, failure, or review gate wakes the coordinator, follow the returned receipt and existing reply/gate commands. See [the orchestration guide](skill-guides/orchestration.md) and [automatic Run instructions](skill-guides/orchestration/references/coordinator-loop.md#automatic-runs).

## Focused tests

```sh
pnpm test src/main/runtime/orchestration/automatic-run/automatic-run-executor.test.ts src/main/runtime/orchestration/automatic-run/automatic-run-event-failure.test.ts src/main/runtime/orchestration/automatic-run/automatic-run-task-brief.test.ts src/main/runtime/orchestration/db/automatic-runs/workflow-apply.test.ts src/main/runtime/orchestration/db/schema/migrate-v47.test.ts src/main/runtime/rpc/methods/orchestration/automatic/automatic-run-host.test.ts src/cli/handlers/orchestration-run-cli.test.ts --maxWorkers=2
```

Coverage includes task order, parallel limits, duplicate completion, failure isolation, review gates, pause/cancel, recovery, workspace serialization, workflow versioning, and the absence of intermediate coordinator notifications on an ordinary chain.

## Attribution and license

Based on Orca by Stably / Lovecast Inc. Upstream copyright notices and the [MIT license](LICENSE) are retained. The original product documentation is preserved in [README.upstream.md](README.upstream.md). This repository is independently maintained and does not imply upstream endorsement.
