import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { OrchestrationWorkflow } from '../../../../../shared/orchestration-workflow'
import { OrchestrationDb } from '../orchestration-db'
import type { RunRow, TaskRow } from '../../types'

let db: OrchestrationDb

beforeEach(() => {
  db = new OrchestrationDb(':memory:')
})

afterEach(() => {
  db.close()
})

function run(maxParallel = 2): RunRow {
  return db.createRun({
    objective: 'workflow',
    coordinatorHandle: 'term_coord',
    coordinatorPaneKey: 'tab:leaf',
    executionMode: 'automatic',
    maxParallel,
    workspaceId: 'wt_main'
  })
}

function apply(runId: string, expectedVersion: number, workflow: unknown): void {
  db.applyOrchestrationWorkflow({
    runId,
    expectedVersion,
    workflow: OrchestrationWorkflow.parse(workflow)
  })
}

function tasks(runId: string): TaskRow[] {
  return db.listTasks({ runId })
}

describe('applyOrchestrationWorkflow', () => {
  it('materializes keys into Task ids and bumps the version atomically', () => {
    const r = run()
    apply(r.id, 0, {
      maxParallel: 2,
      tasks: [
        { key: 'A', spec: 'Implement A' },
        { key: 'B', spec: 'Implement B', dependsOn: ['A'] }
      ]
    })
    const a = tasks(r.id).find((task) => task.source_key === 'A') as TaskRow
    const b = tasks(r.id).find((task) => task.source_key === 'B') as TaskRow
    expect(a.status).toBe('ready')
    expect(b.status).toBe('pending')
    expect(JSON.parse(b.deps)).toEqual([a.id])
    expect(db.getRun(r.id)).toMatchObject({ workflow_version: 1, max_parallel: 2 })
  })

  it('updates only not-yet-started Tasks and bumps the version', () => {
    const r = run()
    apply(r.id, 0, { tasks: [{ key: 'A', spec: 'old' }] })
    apply(r.id, 1, { tasks: [{ key: 'A', spec: 'new' }] })
    expect(tasks(r.id)[0]?.spec).toBe('new')
    expect(db.getRun(r.id)?.workflow_version).toBe(2)
  })

  it('refuses to remove or rewrite a started Task', () => {
    const r = run()
    apply(r.id, 0, {
      tasks: [
        { key: 'A', spec: 'A' },
        { key: 'B', spec: 'B', dependsOn: ['A'] }
      ]
    })
    const a = tasks(r.id).find((task) => task.source_key === 'A') as TaskRow
    db.setRunExecutionState(r.id, 'running')
    db.createStartingWorkerDispatch({
      taskId: a.id,
      startOptions: {},
      creator: { kind: 'system' },
      maxDepth: 8
    })

    expect(() => apply(r.id, 1, { tasks: [{ key: 'B', spec: 'B' }] })).toThrow(/already started/)
    expect(() => apply(r.id, 1, { tasks: [{ key: 'A', spec: 'changed' }] })).toThrow(
      /only not-yet-started/
    )
    expect(db.getRun(r.id)?.workflow_version).toBe(1)
  })

  it('rejects stale versions without changing the DAG', () => {
    const r = run()
    apply(r.id, 0, { tasks: [{ key: 'A', spec: 'A' }] })
    expect(() => apply(r.id, 0, { tasks: [{ key: 'A', spec: 'other' }] })).toThrow(
      /Workflow version is 1/
    )
    expect(tasks(r.id)[0]?.spec).toBe('A')
  })

  it('rejects cycles and unknown dependencies before writing rows', () => {
    const r = run()
    expect(() =>
      apply(r.id, 0, {
        tasks: [
          { key: 'A', spec: 'A', dependsOn: ['B'] },
          { key: 'B', spec: 'B', dependsOn: ['A'] }
        ]
      })
    ).toThrow(/cycle/)
    expect(() =>
      apply(r.id, 0, {
        tasks: [{ key: 'A', spec: 'A', dependsOn: ['missing'] }]
      })
    ).toThrow(/unknown Task/)
    expect(tasks(r.id)).toHaveLength(0)
  })

  it('shares pause, capacity and gate guards with manual starts in an automatic Run', () => {
    const r = run(1)
    apply(r.id, 0, { tasks: [{ key: 'A', spec: 'A' }] })
    const a = tasks(r.id)[0] as TaskRow

    expect(() =>
      db.createStartingWorkerDispatch({
        taskId: a.id,
        startOptions: {},
        creator: { kind: 'system' },
        maxDepth: 8
      })
    ).toThrow(/preparing/)

    db.setRunExecutionState(r.id, 'running')
    db.createStartingWorkerDispatch({
      taskId: a.id,
      startOptions: {},
      creator: { kind: 'system' },
      maxDepth: 8
    })
    apply(r.id, 1, {
      maxParallel: 1,
      tasks: [
        { key: 'A', spec: 'A' },
        { key: 'B', spec: 'B' }
      ]
    })
    const b = tasks(r.id).find((task) => task.source_key === 'B') as TaskRow
    expect(() =>
      db.createStartingWorkerDispatch({
        taskId: b.id,
        startOptions: {},
        creator: { kind: 'system' },
        maxDepth: 8
      })
    ).toThrow(/parallel limit/)

    db.completeDispatch(
      (
        db.db.prepare('SELECT id FROM dispatch_contexts WHERE task_id = ?').get(a.id) as {
          id: string
        }
      ).id
    )
    db.setRunExecutionState(r.id, 'paused')
    expect(() =>
      db.createStartingWorkerDispatch({
        taskId: b.id,
        startOptions: {},
        creator: { kind: 'system' },
        maxDepth: 8
      })
    ).toThrow(/paused/)
  })

  it('keeps manual Runs out of the workflow path', () => {
    const manual = db.createRun({
      objective: 'manual',
      coordinatorHandle: 'term_coord',
      coordinatorPaneKey: 'tab:leaf'
    })
    expect(() => apply(manual.id, 0, { tasks: [{ key: 'A', spec: 'A' }] })).toThrow(
      /manually operated/
    )
  })
})
