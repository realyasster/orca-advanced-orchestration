import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { OrchestrationDb } from '../db'
import { OrchestrationDb as OrchestrationDbCtor } from '../db/orchestration-db'
import { OrchestrationWorkflow } from '../../../../shared/orchestration-workflow'
import type { RunRow, TaskRow } from '../types'
import {
  AutomaticRunExecutor,
  type AutomaticLaunchRequest,
  type AutomaticRunHost
} from './automatic-run-executor'

const COORD = 'term_coord'
const PANE = 'tab_1:leaf_1'
const WORKSPACE = 'wt_main'

let db: OrchestrationDb
let executor: AutomaticRunExecutor
let launches: AutomaticLaunchRequest[]
let host: AutomaticRunHost

beforeEach(() => {
  db = new OrchestrationDbCtor(':memory:')
  launches = []
  host = {
    launchTask: vi.fn(async (request: AutomaticLaunchRequest) => {
      launches.push(request)
      const started = db.createStartingWorkerDispatch({
        taskId: request.task.id,
        startOptions: { worktree: request.worktree ?? null },
        creator: { kind: 'system' },
        maxDepth: 8
      })
      db.markWorkerDispatchReady(started.dispatch.id)
      return {
        dispatchId: started.dispatch.id,
        worktreeId: request.workspaceKey ?? WORKSPACE
      }
    }),
    stopDispatch: vi.fn(async (dispatchId: string) => {
      db.completeDispatch(dispatchId)
      return { state: 'stopped', stopped: true }
    }),
    notifyRun: vi.fn()
  }
  executor = new AutomaticRunExecutor(db, host)
})

afterEach(() => {
  db.close()
})

function createRun(workflow: unknown, maxParallel = 2): RunRow {
  const run = db.createRun({
    objective: 'Ship the feature',
    coordinatorHandle: COORD,
    coordinatorPaneKey: PANE,
    executionMode: 'automatic',
    maxParallel,
    workspaceId: WORKSPACE
  })
  db.applyOrchestrationWorkflow({
    runId: run.id,
    expectedVersion: 0,
    workflow: OrchestrationWorkflow.parse(workflow)
  })
  db.setRunExecutionState(run.id, 'running')
  return run
}

function taskByKey(runId: string, key: string): TaskRow {
  const task = db.db
    .prepare('SELECT * FROM tasks WHERE run_id = ? AND source_key = ?')
    .get(runId, key) as TaskRow | undefined
  if (!task) {
    throw new Error(`Missing task ${key}`)
  }
  return task
}

function complete(task: TaskRow, summary = 'done', reviewVerdict?: string): void {
  const dispatch = db.db
    .prepare(
      "SELECT id FROM dispatch_contexts WHERE task_id = ? AND status IN ('pending','dispatched') ORDER BY rowid DESC LIMIT 1"
    )
    .get(task.id) as { id: string }
  const settled = db.settleWorkerReport({
    taskId: task.id,
    dispatchId: dispatch.id,
    outcome: 'succeeded',
    result: JSON.stringify({
      summary,
      evidence: ['test.txt'],
      ...(reviewVerdict ? { reviewVerdict } : {})
    })
  })
  expect(settled.action).toBe('settled')
}

function fail(task: TaskRow, summary = 'failed'): void {
  const dispatch = db.db
    .prepare(
      "SELECT id FROM dispatch_contexts WHERE task_id = ? AND status IN ('pending','dispatched') ORDER BY rowid DESC LIMIT 1"
    )
    .get(task.id) as { id: string }
  db.settleWorkerReport({
    taskId: task.id,
    dispatchId: dispatch.id,
    outcome: 'failed',
    result: JSON.stringify({ summary, evidence: [] })
  })
}

const TWO_STEP = {
  tasks: [
    { key: 'A', spec: 'Implement A', review: false },
    { key: 'B', spec: 'Implement B', dependsOn: ['A'] }
  ]
}

const FAN_IN = {
  tasks: [
    { key: 'A', spec: 'Implement A' },
    { key: 'B', spec: 'Implement B' },
    { key: 'C', spec: 'Combine A and B', dependsOn: ['A', 'B'] }
  ]
}

describe('AutomaticRunExecutor', () => {
  it('starts A, then B only after A completes, and wakes once for the final report', async () => {
    const run = createRun(TWO_STEP)
    executor.trigger(run.id)
    await executor.drain(run.id)

    expect(launches.map((request) => request.task.source_key)).toEqual(['A'])
    expect(taskByKey(run.id, 'B').status).toBe('pending')

    complete(taskByKey(run.id, 'A'))
    executor.trigger(run.id)
    await executor.drain(run.id)

    expect(launches.map((request) => request.task.source_key)).toEqual(['A', 'B'])
    expect(taskByKey(run.id, 'B').status).toBe('dispatched')
    expect(host.notifyRun).not.toHaveBeenCalled()

    complete(taskByKey(run.id, 'B'))
    executor.trigger(run.id)
    await executor.drain(run.id)

    const settled = db.getRun(run.id) as RunRow
    expect(settled.execution_state).toBe('settled')
    expect(settled.execution_outcome).toBe('completed')
    expect(settled.final_report_delivered_at).not.toBeNull()
    expect(host.notifyRun).toHaveBeenCalledTimes(1)
    const wake = db.listQueuedAutomaticWakes(run.id)
    expect(wake).toHaveLength(0)
  })

  it('runs A and B in parallel and starts C only after both complete', async () => {
    const run = createRun(FAN_IN, 2)
    executor.trigger(run.id)
    await executor.drain(run.id)

    expect(launches.map((request) => request.task.source_key).sort()).toEqual(['A', 'B'])
    expect(taskByKey(run.id, 'C').status).toBe('pending')

    complete(taskByKey(run.id, 'A'))
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(launches.map((request) => request.task.source_key)).not.toContain('C')

    complete(taskByKey(run.id, 'B'))
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(launches.map((request) => request.task.source_key)).toContain('C')
  })

  it('never exceeds the Run parallelism limit', async () => {
    const run = createRun(
      {
        maxParallel: 2,
        tasks: [
          { key: 'A', spec: 'A' },
          { key: 'B', spec: 'B' },
          { key: 'C', spec: 'C' },
          { key: 'D', spec: 'D' }
        ]
      },
      2
    )
    executor.trigger(run.id)
    await executor.drain(run.id)

    expect(launches).toHaveLength(2)
    const active = db.db
      .prepare(
        "SELECT COUNT(*) AS count FROM dispatch_contexts WHERE run_id = ? AND status IN ('pending','dispatched')"
      )
      .get(run.id) as { count: number }
    expect(active.count).toBe(2)
  })

  it('does not apply a duplicate completion twice or wake twice', async () => {
    const run = createRun(TWO_STEP)
    executor.trigger(run.id)
    await executor.drain(run.id)
    const taskA = taskByKey(run.id, 'A')
    complete(taskA)
    const dispatch = db.db
      .prepare('SELECT id FROM dispatch_contexts WHERE task_id = ? LIMIT 1')
      .get(taskA.id) as { id: string }
    const duplicate = db.settleWorkerReport({
      taskId: taskA.id,
      dispatchId: dispatch.id,
      outcome: 'succeeded',
      result: '{}'
    })
    expect(duplicate).toEqual({ action: 'settled', outcome: 'succeeded', duplicate: true })
    executor.trigger(run.id)
    await executor.drain(run.id)
    complete(taskByKey(run.id, 'B'))
    executor.trigger(run.id)
    await executor.drain(run.id)

    const events = db.db
      .prepare(
        "SELECT COUNT(*) AS count FROM automatic_run_events WHERE run_id = ? AND kind = 'task_completed'"
      )
      .get(run.id) as { count: number }
    expect(events.count).toBe(2)
    expect(host.notifyRun).toHaveBeenCalledTimes(1)
  })

  it('waits the failed branch and wakes the coordinator while an independent branch still starts', async () => {
    const run = createRun(FAN_IN, 2)
    executor.trigger(run.id)
    await executor.drain(run.id)
    fail(taskByKey(run.id, 'A'))
    executor.trigger(run.id)
    await executor.drain(run.id)

    expect(taskByKey(run.id, 'C').status).toBe('pending')
    expect(host.notifyRun).toHaveBeenCalledTimes(1)
    // A failed branch waits for a coordinator decision; settling would block retry/workflow-apply.
    expect(db.getRun(run.id)?.execution_state).toBe('running')
    const mail = db.getUnreadMessages(`run:${run.id}`)
    expect(mail[0]?.body).toContain('failed')
  })

  it('keeps downstream blocked when a review Task fails', async () => {
    const run = createRun({
      tasks: [
        { key: 'A', spec: 'Implement A' },
        { key: 'R', spec: 'Review A', dependsOn: ['A'], reviewRole: 'review', reviewOf: 'A' },
        { key: 'B', spec: 'Ship A', dependsOn: ['A'] }
      ]
    })
    executor.trigger(run.id)
    await executor.drain(run.id)
    complete(taskByKey(run.id, 'A'))
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(launches.map((request) => request.task.source_key)).toContain('R')

    fail(taskByKey(run.id, 'R'), 'review crashed')
    executor.trigger(run.id)
    await executor.drain(run.id)

    expect(launches.map((request) => request.task.source_key)).not.toContain('B')
    expect(db.getRun(run.id)?.execution_state).toBe('running')
  })

  it('opens a review gate and creates a correction chain after changes_requested', async () => {
    const run = createRun({
      tasks: [
        { key: 'A', spec: 'Implement A', review: true },
        { key: 'B', spec: 'Ship A', dependsOn: ['A'] }
      ]
    })
    executor.trigger(run.id)
    await executor.drain(run.id)
    complete(taskByKey(run.id, 'A'))
    executor.trigger(run.id)
    await executor.drain(run.id)

    const gates = db.listPendingGatesForRun(run.id)
    expect(gates).toHaveLength(1)
    expect(launches.map((request) => request.task.source_key)).not.toContain('B')
    expect(host.notifyRun).toHaveBeenCalledTimes(1)

    db.resolveGate(gates[0].id, 'changes_requested')
    executor.trigger(run.id)
    await executor.drain(run.id)

    const correction = db.db
      .prepare("SELECT * FROM tasks WHERE run_id = ? AND review_role = 'correction'")
      .get(run.id) as TaskRow
    expect(correction).toBeDefined()
    expect(correction.correction_round).toBe(1)
    expect(launches.at(-1)?.workspaceKey).toBe(WORKSPACE)
    expect(launches.map((request) => request.task.source_key)).not.toContain('B')

    complete(correction, 'fixed')
    executor.trigger(run.id)
    await executor.drain(run.id)
    const secondGate = db.listPendingGatesForRun(run.id)
    expect(secondGate).toHaveLength(1)
    expect(launches.map((request) => request.task.source_key)).not.toContain('B')

    db.resolveGate(secondGate[0].id, 'Approved, minor notes')
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(launches.map((request) => request.task.source_key)).toContain('B')
  })

  it('keeps downstream blocked when a correction Task fails', async () => {
    const run = createRun({
      tasks: [
        { key: 'A', spec: 'Implement A', review: true },
        { key: 'B', spec: 'Ship A', dependsOn: ['A'] }
      ]
    })
    executor.trigger(run.id)
    await executor.drain(run.id)
    complete(taskByKey(run.id, 'A'))
    executor.trigger(run.id)
    await executor.drain(run.id)
    const gate = db.listPendingGatesForRun(run.id)[0]
    db.resolveGate(gate.id, 'changes_requested: add tests')
    executor.trigger(run.id)
    await executor.drain(run.id)

    const correction = db.db
      .prepare("SELECT * FROM tasks WHERE run_id = ? AND review_role = 'correction'")
      .get(run.id) as TaskRow
    fail(correction, 'correction failed')
    executor.trigger(run.id)
    await executor.drain(run.id)

    expect(launches.map((request) => request.task.source_key)).not.toContain('B')
    expect(db.getRun(run.id)?.execution_state).toBe('running')
  })

  it('durably records a failure wake behind an unread wake, then delivers it after the check', async () => {
    const run = createRun({ tasks: [{ key: 'A', spec: 'A' }] })
    executor.trigger(run.id)
    await executor.drain(run.id)
    db.insertMessage({
      from: 'orca:auto',
      to: `run:${run.id}`,
      subject: 'older decision',
      body: 'older decision',
      type: 'status',
      priority: 'high',
      runId: run.id,
      payload: JSON.stringify({ automaticRunWake: true, runId: run.id })
    })

    fail(taskByKey(run.id, 'A'), 'worker failed')
    executor.trigger(run.id)
    await executor.drain(run.id)
    const queued = db.db
      .prepare("SELECT reason FROM automatic_run_wakes WHERE run_id = ? AND status = 'queued'")
      .all(run.id) as { reason: string }[]
    expect(queued.some((wake) => wake.reason.includes('worker failed'))).toBe(true)

    const unread = db.getUnreadMessages(`run:${run.id}`)
    db.markAsRead(unread.map((message) => message.id))
    executor.trigger(run.id)
    await executor.drain(run.id)
    const delivered = db.getUnreadMessages(`run:${run.id}`)
    expect(delivered.some((message) => message.body.includes('worker failed'))).toBe(true)
  })

  it('recovers an interrupted launch as start_unknown instead of starting a second worker', async () => {
    const run = createRun(TWO_STEP)
    const taskA = taskByKey(run.id, 'A')
    const started = db.createStartingWorkerDispatch({
      taskId: taskA.id,
      startOptions: {},
      creator: { kind: 'system' },
      maxDepth: 8
    })
    expect(db.getTask(taskA.id)?.status).toBe('dispatched')

    executor.recover()
    await executor.drain(run.id)

    expect(db.getWorkerDispatch(started.dispatch.id)?.state).toBe('start_unknown')
    expect(taskByKey(run.id, 'A').status).toBe('blocked')
    expect(launches).toHaveLength(0)
    expect(host.notifyRun).toHaveBeenCalledTimes(1)
  })

  it('keeps an unproven stop visible as cancelling instead of claiming cancellation', async () => {
    const run = createRun({ maxParallel: 1, tasks: [{ key: 'A', spec: 'A' }] }, 1)
    executor.trigger(run.id)
    await executor.drain(run.id)
    host.stopDispatch = vi.fn(async () => ({ state: 'stop_unknown', stopped: false }))

    db.setRunExecutionState(run.id, 'cancelling', { cancelReason: 'user' })
    executor.trigger(run.id)
    await executor.drain(run.id)

    expect(db.getRun(run.id)?.execution_state).toBe('cancelling')
    expect(db.getRun(run.id)?.execution_outcome).toBeNull()
    expect(host.notifyRun).toHaveBeenCalledTimes(1)
    const mail = db.getUnreadMessages(`run:${run.id}`)
    expect(mail[0]?.body).toContain('stop_unknown')
  })

  it('replays a committed completion after restart and starts the dependent Task', async () => {
    const run = createRun(TWO_STEP)
    executor.trigger(run.id)
    await executor.drain(run.id)
    complete(taskByKey(run.id, 'A'))
    // No trigger: this is the crash window between the result commit and the next launch.
    const recovered = new AutomaticRunExecutor(db, host)
    recovered.recover()
    await recovered.drain(run.id)

    expect(launches.map((request) => request.task.source_key)).toEqual(['A', 'B'])
  })

  it('serializes two write Tasks that name the same workspace', async () => {
    const run = createRun(
      {
        tasks: [
          { key: 'A', spec: 'A', worktree: 'id:wt_shared' },
          { key: 'B', spec: 'B', worktree: 'id:wt_shared' }
        ]
      },
      2
    )
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(launches.map((request) => request.task.source_key)).toEqual(['A'])

    complete(taskByKey(run.id, 'A'))
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(launches.map((request) => request.task.source_key)).toEqual(['A', 'B'])
  })

  it('makes no coordinator wake between the first launch and the final report', async () => {
    const run = createRun(TWO_STEP)
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(host.notifyRun).toHaveBeenCalledTimes(0)
    complete(taskByKey(run.id, 'A'))
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(host.notifyRun).toHaveBeenCalledTimes(0)
    complete(taskByKey(run.id, 'B'))
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(host.notifyRun).toHaveBeenCalledTimes(1)
  })

  it('pause blocks new launches while running workers continue; cancel settles only proven stops', async () => {
    const run = createRun({ ...FAN_IN, maxParallel: 1 }, 1)
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(launches).toHaveLength(1)

    db.setRunExecutionState(run.id, 'paused', { pauseReason: 'user' })
    complete(taskByKey(run.id, launches[0].task.source_key as string))
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(launches).toHaveLength(1)

    db.setRunExecutionState(run.id, 'running')
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(launches).toHaveLength(2)

    db.setRunExecutionState(run.id, 'cancelling', { cancelReason: 'stop' })
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(db.getRun(run.id)?.execution_state).toBe('settled')
    expect(db.getRun(run.id)?.execution_outcome).toBe('cancelled')
  })

  it('writes the settled state and final report together, and recovers a report lost after settling', async () => {
    const run = createRun({ tasks: [{ key: 'A', spec: 'A' }] })
    executor.trigger(run.id)
    await executor.drain(run.id)
    complete(taskByKey(run.id, 'A'))
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(db.getRun(run.id)?.final_report_delivered_at).not.toBeNull()

    // Simulate the pre-transaction crash: settled row, delivered wake, but no final timestamp/message.
    db.db.prepare('UPDATE runs SET final_report_delivered_at = NULL WHERE id = ?').run(run.id)
    db.db
      .prepare(
        "UPDATE automatic_run_wakes SET status = 'queued', message_id = NULL WHERE event_key = ?"
      )
      .run(`settled:${run.id}`)
    db.db
      .prepare(
        "DELETE FROM messages WHERE run_id = ? AND json_extract(payload, '$.finalReport') = 1"
      )
      .run(run.id)

    const recovered = new AutomaticRunExecutor(db, host)
    recovered.recover()

    expect(db.getRun(run.id)?.final_report_delivered_at).not.toBeNull()
    const report = db.db
      .prepare(
        "SELECT COUNT(*) AS count FROM messages WHERE run_id = ? AND json_extract(payload, '$.finalReport') = 1"
      )
      .get(run.id) as { count: number }
    expect(report.count).toBe(1)
  })

  it('makes a write wait for an active read worker in the same workspace', async () => {
    const run = createRun(
      {
        tasks: [
          { key: 'READ', spec: 'Verify', worktree: 'id:wt_shared', workspaceUsage: 'read' },
          { key: 'WRITE', spec: 'Change', worktree: 'id:wt_shared' }
        ]
      },
      2
    )
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(launches.map((request) => request.task.source_key)).toEqual(['READ'])

    complete(taskByKey(run.id, 'READ'))
    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(launches.map((request) => request.task.source_key)).toEqual(['READ', 'WRITE'])
  })

  it('does not launch a stale Task snapshot after a workflow update during launch', async () => {
    const run = createRun({
      tasks: [
        { key: 'A', spec: 'A', worktree: 'new-child' },
        { key: 'B', spec: 'old B', worktree: 'new-child' }
      ]
    })
    let updated = false
    const launch = host.launchTask
    host.launchTask = async (request) => {
      if (!updated) {
        updated = true
        db.applyOrchestrationWorkflow({
          runId: run.id,
          expectedVersion: db.getRun(run.id)!.workflow_version,
          workflow: OrchestrationWorkflow.parse({
            tasks: [
              { key: 'A', spec: 'A', worktree: 'new-child' },
              { key: 'B', spec: 'new B', worktree: 'new-child' }
            ]
          })
        })
      }
      return launch(request)
    }

    executor.trigger(run.id)
    await executor.drain(run.id)
    expect(launches).toHaveLength(1)

    executor.trigger(run.id)
    await executor.drain(run.id)
    const b = launches.find((request) => request.task.source_key === 'B')
    expect(b?.task.spec).toBe('new B')
  })

  it('isolates a throwing launch so other ready Tasks still start', async () => {
    const run = createRun({
      tasks: [
        { key: 'A', spec: 'A' },
        { key: 'B', spec: 'B' }
      ]
    })
    const launch = host.launchTask
    host.launchTask = async (request) => {
      if (request.task.source_key === 'A') {
        throw new Error('adapter crashed')
      }
      return launch(request)
    }

    executor.trigger(run.id)
    await executor.drain(run.id)

    expect(taskByKey(run.id, 'A').status).toBe('blocked')
    expect(launches.map((request) => request.task.source_key)).toContain('B')
  })

  it('treats a leading approved verdict as approval', () => {
    expect(db.isApprovedGateResolution('Approved, minor notes')).toBe(true)
    expect(db.isApprovedGateResolution('changes_requested: tests missing')).toBe(false)
  })
})
