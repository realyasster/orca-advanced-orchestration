# Coordinator loop

## Task DAGs

A Task needs a Run, so create one first. Workers editing the same files at once
need separate workspaces.

```text
ORCA orchestration run-create --objective "<goal>"
ORCA orchestration task-create --spec "<dependent work>" --deps <json_array>
ORCA orchestration task-list --ready --brief
ORCA orchestration worker-start --task <task_id> --worktree current --agent codex
```

On every wake, start the Tasks `task-list --ready` shows.

## Automatic Runs

Create the Run with `--mode automatic`, apply one workflow, then start it:

```text
ORCA orchestration run-create --objective "<goal>" --mode automatic --max-parallel 2
ORCA orchestration workflow-apply --run <run_id> --workflow-file <path|-> --expected-version 0
ORCA orchestration run-start --id <run_id>
```

The runtime executor launches ready Tasks; do not dispatch them yourself and do
not poll. Wakes are reserved for worker questions, failures, review gates and the
final report. Resolve a gate with `gate-resolve`; pause/resume/cancel with the
Run commands. Only not-yet-started Tasks can be changed by another
`workflow-apply`; pass the version the Run reported.

## Several Runs

A later `run-create` keeps your earlier Runs: their mail still wakes you, but
commands without `--run` use the newest Run, so pass `--run <id>` for an earlier
one. `run-use` keeps only the Run it names.
