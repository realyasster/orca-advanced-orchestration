import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { OrchestrationDb } from '../../../../orchestration/db/orchestration-db'
import type { OrcaRuntimeService } from '../../../../orca-runtime'
import { OrchestrationWorkflow } from '../../../../../../shared/orchestration-workflow'
import type { RunRow, TaskRow } from '../../../../orchestration/types'
import { getActiveDispatchForTask } from '../../../../orchestration/db/dispatch-context/task-dispatch-reconciliation'

const startLocalWorker = vi.hoisted(() => vi.fn())
vi.mock('../worker/local-worker-start', () => ({ startLocalWorker }))

const { launchAutomaticTask } = await import('./automatic-run-host')

let db: OrchestrationDb
let runtime: OrcaRuntimeService
let run: RunRow
let taskA: TaskRow
let taskB: TaskRow

beforeEach(() => {
  db = new OrchestrationDb(':memory:')
  run = db.createRun({
    objective: 'host',
    coordinatorHandle: 'term_coord',
    coordinatorPaneKey: 'tab:leaf',
    executionMode: 'automatic',
    maxParallel: 2,
    workspaceId: 'wt_main'
  })
  db.applyOrchestrationWorkflow({
    runId: run.id,
    expectedVersion: 0,
    workflow: OrchestrationWorkflow.parse({
      tasks: [
        { key: 'A', spec: 'A' },
        { key: 'B', spec: 'B' }
      ]
    })
  })
  db.setRunExecutionState(run.id, 'running')
  taskA = taskByKey('A')
  taskB = taskByKey('B')
  // SAFETY: launchAutomaticTask reaches only these settings/database surfaces before the launch.
  runtime = {
    getOrchestrationDb: () => db,
    getClientSettings: () => null,
    requireStore: () => ({ getSettings: () => null })
  } as unknown as OrcaRuntimeService
  startLocalWorker.mockReset()
})

afterEach(() => {
  db.close()
})

function taskByKey(key: string): TaskRow {
  return db.db
    .prepare('SELECT * FROM tasks WHERE run_id = ? AND source_key = ?')
    .get(run.id, key) as TaskRow
}

function request(task: TaskRow) {
  return {
    run,
    task,
    options: { workspaceUsage: 'write' as const },
    worktree: 'id:wt_main',
    workspaceKey: 'wt_main'
  }
}

describe('automatic worker launch acceptance', () => {
  it('treats an error with a live Dispatch as an unknown launch, not a refused preflight', async () => {
    const started = db.createStartingWorkerDispatch({
      taskId: taskA.id,
      startOptions: {},
      creator: { kind: 'system' },
      maxDepth: 8
    })
    startLocalWorker.mockRejectedValue(new Error('transport closed'))

    const result = await launchAutomaticTask(runtime, request(taskA))

    expect(result.dispatchId).toBe(started.dispatch.id)
    expect(result.error).toBeUndefined()
    const event = db.db
      .prepare("SELECT kind FROM automatic_run_events WHERE run_id = ? AND kind = 'launch_unknown'")
      .get(run.id) as { kind: string } | undefined
    expect(event?.kind).toBe('launch_unknown')
    expect(getActiveDispatchForTask(db, taskA.id)?.id).toBe(started.dispatch.id)
  })

  it('reports a refusal when no Dispatch was accepted', async () => {
    startLocalWorker.mockRejectedValue(new Error('agent_unconfigured'))

    const result = await launchAutomaticTask(runtime, request(taskB))

    expect(result.dispatchId).toBeUndefined()
    expect(result.error).toContain('agent_unconfigured')
    expect(getActiveDispatchForTask(db, taskB.id)).toBeUndefined()
  })
})
