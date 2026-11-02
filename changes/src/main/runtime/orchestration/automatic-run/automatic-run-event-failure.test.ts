import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { OrchestrationDb } from '../db/orchestration-db'
import { OrchestrationWorkflow } from '../../../../shared/orchestration-workflow'
import type { RunRow, TaskRow } from '../types'
import { AutomaticRunExecutor, type AutomaticRunHost } from './automatic-run-executor'
import type * as ReviewModule from './automatic-run-review'

vi.mock('./automatic-run-review', async (importOriginal) => {
  const actual = await importOriginal<typeof ReviewModule>()
  return {
    ...actual,
    afterTaskCompleted: () => {
      throw new Error('gate write failed')
    }
  }
})

let db: OrchestrationDb
let host: AutomaticRunHost
let launches: string[]

beforeEach(() => {
  db = new OrchestrationDb(':memory:')
  launches = []
  host = {
    launchTask: async (request) => {
      launches.push(request.task.source_key ?? request.task.id)
      const started = db.createStartingWorkerDispatch({
        taskId: request.task.id,
        startOptions: {},
        creator: { kind: 'system' },
        maxDepth: 8
      })
      db.markWorkerDispatchReady(started.dispatch.id)
      return { dispatchId: started.dispatch.id }
    },
    stopDispatch: async () => ({ state: 'stopped', stopped: true }),
    notifyRun: vi.fn()
  }
})

afterEach(() => {
  db.close()
})

function createRun(): RunRow {
  const run = db.createRun({
    objective: 'failure handling',
    coordinatorHandle: 'term_coord',
    coordinatorPaneKey: 'tab:leaf',
    executionMode: 'automatic',
    workspaceId: 'wt_main'
  })
  db.applyOrchestrationWorkflow({
    runId: run.id,
    expectedVersion: 0,
    workflow: OrchestrationWorkflow.parse({
      tasks: [
        { key: 'A', spec: 'A' },
        { key: 'B', spec: 'B', dependsOn: ['A'] }
      ]
    })
  })
  db.setRunExecutionState(run.id, 'running')
  return run
}

function taskByKey(runId: string, key: string): TaskRow {
  return db.db
    .prepare('SELECT * FROM tasks WHERE run_id = ? AND source_key = ?')
    .get(runId, key) as TaskRow
}

function complete(task: TaskRow): void {
  const dispatch = db.db
    .prepare(
      "SELECT id FROM dispatch_contexts WHERE task_id = ? AND status IN ('pending','dispatched') LIMIT 1"
    )
    .get(task.id) as { id: string }
  db.settleWorkerReport({
    taskId: task.id,
    dispatchId: dispatch.id,
    outcome: 'succeeded',
    result: JSON.stringify({ summary: 'done', evidence: [] })
  })
}

describe('automatic event handler failure', () => {
  it('parks the branch behind a gate and wakes the coordinator instead of failing silently', async () => {
    const run = createRun()
    const executor = new AutomaticRunExecutor(db, host)
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(launches).toEqual(['A'])

    complete(taskByKey(run.id, 'A'))
    executor.trigger(run.id)
    await executor.drain(run.id)

    expect(db.getTask(taskByKey(run.id, 'A').id)?.status).toBe('completed')
    expect(db.listPendingGatesForRun(run.id)).toHaveLength(1)
    expect(launches).toEqual(['A'])
    expect(db.getRun(run.id)?.execution_state).toBe('running')
    const event = db.db
      .prepare(
        "SELECT state FROM automatic_run_events WHERE run_id = ? AND kind = 'task_completed'"
      )
      .get(run.id) as { state: string }
    expect(event.state).toBe('failed')
    const mail = db.getUnreadMessages(`run:${run.id}`)
    expect(
      mail.some((message) => message.body.includes('Automatic executor could not process'))
    ).toBe(true)
  })
})
