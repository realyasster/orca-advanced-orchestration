# Orca Advanced Orchestration

Automatically coordinates tasks between agents such as Codex and Claude in Orca. Define a workflow once: dependent tasks start when their prerequisites finish, and independent tasks run in parallel.

Example: **Write code → Run tests and review in parallel → Fix if needed → Report results.**

## What does it do?

- Reduces manual agent launches and repeated status checks.
- Manages task dependencies, shared workspaces, and review decisions.
- Supports pausing, resuming, and cancelling workflows.
- Adds a persistent **Todo** column to the agent board, left of the status columns; items are scoped per workspace, never launch agents, and stay separate from agent state.
- **Orchestrator** and **Todo** can be selected independently at install time; only the chosen file set is written from the single bundle.
- Aims to reduce unnecessary coordinator calls during routine transitions; worker agents still consume tokens.

## Installation

This repository is a **change bundle for the Orca v1.4.246 source code**. The installation tool backs up source files and applies the changes; you then need to build Orca. It is not a standalone application or plugin.

Quick start (Windows PowerShell):

```powershell
irm https://raw.githubusercontent.com/realyasster/orca-advanced-orchestration/v1.4.246-todo.1/install.ps1 | iex
```

Choose **Orchestrator** and **Todo** independently in the installer menu.

**[Installation and usage guide](docs/USAGE.en.md)** · [Example workflow](examples/workflow.json)

[Türkçe](README.md) · [Technical design](docs/DESIGN.md) · [Test results and known limitations](docs/VALIDATION.md) · [MIT license](LICENSE)
