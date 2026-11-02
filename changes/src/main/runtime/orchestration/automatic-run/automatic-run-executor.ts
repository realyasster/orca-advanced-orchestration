import type { OrchestrationDb } from '../db'
import type {
  AutomaticRunEventRow,
  AutomaticRunWakeRow,
  DispatchContextRow,
  RunRow,
  TaskRow
} from '../types'
import type { OrchestrationTaskExecutionOptions } from '../../../../shared/orchestration-workflow'
import {
  markAutomaticRunEventProcessed,
  recordAutomaticRunEvent
} from '../db/automatic-runs/automatic-run-store'
import {
  afterGateResolved,
  afterTaskCompleted,
  parseJson,
  pendingGateAttention,
  type AttentionEvent
} from './automatic-run-review'
import { handleAutomaticEventFailure } from './automatic-run-event-failure'
import { activeDispatches, launchReadyTasks } from './automatic-run-launch'
import { recoverFinalReports, settleIfFinished, settleRun } from './automatic-run-settlement'

export type AutomaticLaunchRequest = {
  run: RunRow
  task: TaskRow
  options: OrchestrationTaskExecutionOptions
  worktree: string | undefined
  workspaceKey: string | null
}

export type AutomaticLaunchResult = {
  dispatchId?: string
  worktreeId?: string
  error?: string
}

export type AutomaticRunHost = {
  launchTask(request: AutomaticLaunchRequest): Promise<AutomaticLaunchResult>
  stopDispatch(dispatchId: string): Promise<{ state: string; stopped: boolean; reason?: string }>
  notifyRun(runId: string): void
}

const AUTOMATIC_RUN_SENDER = 'orca:auto'

/**
 * Event-driven scheduler for opt-in automatic Runs. It holds no timer and calls no model:
 * lifecycle transactions enqueue outbox rows, and this executor advances the DAG.
 */
export class AutomaticRunExecutor {
  private readonly activeRuns = new Map<string, Promise<void>>()
  private readonly rerunRequested = new Set<string>()

  constructor(
    private readonly db: OrchestrationDb,
    private readonly host: AutomaticRunHost
  ) {}

  /** Startup reconciliation: replay pending outbox rows, verify launch state, then resume safe work. */
  recover(): void {
    for (const run of this.db.listAutomaticRunsForRecovery()) {
      if (run.execution_state !== 'cancelling') {
        this.reconcileInterruptedLaunches(run)
      }
      this.trigger(run.id)
    }
    recoverFinalReports(this.db, this.host)
  }

  /** Tests and callers that need a deterministic hand-off wait for the current loop to drain. */
  async drain(runId: string): Promise<void> {
    for (let guard = 0; guard < 20; guard++) {
      const active = this.activeRuns.get(runId)
      if (!active) {
        return
      }
      await active
    }
  }

  trigger(runId: string): void {
    if (this.activeRuns.has(runId)) {
      this.rerunRequested.add(runId)
      return
    }
    const run = this.runLoop(runId)
    this.activeRuns.set(runId, run)
    void run.finally(() => {
      this.activeRuns.delete(runId)
      if (this.rerunRequested.delete(runId)) {
        this.trigger(runId)
      }
    })
  }

  private async runLoop(runId: string): Promise<void> {
    do {
      this.rerunRequested.delete(runId)
      try {
        await this.tick(runId)
      } catch (error) {
        console.warn('[automatic-run] tick failed', runId, error)
      }
    } while (this.rerunRequested.has(runId))
  }

  private async tick(runId: string): Promise<void> {
    const run = this.db.getRun(runId)
    if (!run || run.execution_mode !== 'automatic' || run.execution_state === 'settled') {
      return
    }
    if (run.execution_state === 'cancelling') {
      await this.cancelRun(run)
      return
    }
    if (run.execution_state !== 'running') {
      return
    }
    this.processPendingEvents(run, this.db.listPendingAutomaticRunEvents(run.id))
    const refreshed = this.db.getRun(runId) as RunRow
    this.deliverWakes(refreshed, pendingGateAttention(this.db, refreshed))
    if (this.db.getRun(runId)?.execution_state !== 'running') {
      return
    }
    await launchReadyTasks(this.db, this.host, refreshed)
    settleIfFinished(
      this.db,
      this.host,
      this.db.getRun(runId) as RunRow,
      activeDispatches(this.db, runId).length
    )
  }

  private processPendingEvents(run: RunRow, events: AutomaticRunEventRow[]): void {
    for (const event of events) {
      // Apply, persist the wake, and mark the event processed as one durable unit.
      this.db.db.exec('BEGIN IMMEDIATE')
      try {
        this.applyEvent(run.id, event)
        for (const item of this.eventAttention([event])) {
          this.db.recordAutomaticWake({
            runId: run.id,
            eventId: item.eventId,
            eventKey: item.eventKey,
            reason: item.reason
          })
        }
        markAutomaticRunEventProcessed.call(this.db, event.id)
        this.db.db.exec('COMMIT')
      } catch (error) {
        this.db.db.exec('ROLLBACK')
        console.warn('[automatic-run] event failed', run.id, event.kind, error)
        handleAutomaticEventFailure(this.db, run, event, error)
      }
    }
  }

  private applyEvent(runId: string, event: AutomaticRunEventRow): void {
    const task = event.task_id ? this.db.getTask(event.task_id) : undefined
    if (event.kind === 'task_completed') {
      afterTaskCompleted(this.db, runId, task)
    } else if (event.kind === 'gate_resolved') {
      afterGateResolved(this.db, runId, event)
    }
  }

  private eventAttention(events: AutomaticRunEventRow[]): AttentionEvent[] {
    const attention: AttentionEvent[] = []
    for (const event of events) {
      if (
        !['task_failed', 'launch_failed', 'launch_unknown', 'invalid_completion'].includes(
          event.kind
        )
      ) {
        continue
      }
      const task = event.task_id ? this.db.getTask(event.task_id) : undefined
      const label = task?.task_title ?? task?.display_name ?? event.task_id ?? event.kind
      const payload = parseJson(event.payload)
      const report = typeof payload.result === 'string' ? parseJson(payload.result) : {}
      const detail = eventDetail(payload, report, event.kind)
      attention.push({
        eventId: event.id,
        eventKey: `wake:${event.id}`,
        reason: `${label}: ${detail}`
      })
    }
    return attention
  }

  private deliverWakes(run: RunRow, attention: AttentionEvent[], force = false): void {
    // Record every attention event first, even while an earlier wake is unread, so it is not lost.
    for (const item of attention) {
      this.db.recordAutomaticWake({
        runId: run.id,
        eventId: item.eventId,
        eventKey: item.eventKey,
        reason: item.reason
      })
    }
    // One unread wake summarizes everything pending; queued rows wait for that check.
    if (!force && this.db.hasUnreadAutomaticWake(run.id)) {
      return
    }
    const queued: AutomaticRunWakeRow[] = []
    for (const wake of this.db.listQueuedAutomaticWakes(run.id)) {
      if (!queued.some((row) => row.id === wake.id)) {
        queued.push(wake)
      }
    }
    if (queued.length === 0) {
      return
    }
    const message = this.db.insertMessage({
      from: AUTOMATIC_RUN_SENDER,
      to: `run:${run.id}`,
      subject: `Automatic Run ${run.id} needs a decision`,
      body: queued.map((wake) => wake.reason).join('\n'),
      type: 'decision_gate',
      priority: 'high',
      runId: run.id,
      payload: JSON.stringify({
        automaticRunWake: true,
        runId: run.id,
        reasons: queued.map((wake) => wake.reason),
        eventKeys: queued.map((wake) => wake.event_key)
      })
    })
    for (const wake of queued) {
      this.db.markAutomaticWakeDelivered(wake.id, message.id)
    }
    this.host.notifyRun(run.id)
  }

  private async cancelRun(run: RunRow): Promise<void> {
    const active = activeDispatches(this.db, run.id)
    if (active.length === 0) {
      settleRun(this.db, this.host, run, 'cancelled')
      return
    }
    let allStopped = true
    for (const dispatch of active) {
      const result = await this.host.stopDispatch(dispatch.id)
      if (!result.stopped) {
        allStopped = false
      }
    }
    if (allStopped && activeDispatches(this.db, run.id).length === 0) {
      settleRun(this.db, this.host, run, 'cancelled')
    } else {
      this.deliverWakes(
        run,
        [
          {
            eventId: 'cancel-unknown',
            eventKey: `cancel_unknown:${run.id}`,
            reason:
              'Cancel is waiting: at least one worker stop could not be proven (stop_unknown). The Run is not reported as cancelled.'
          }
        ],
        true
      )
    }
  }

  private reconcileInterruptedLaunches(run: RunRow): void {
    const rows = this.db.db
      .prepare(
        `SELECT d.* FROM dispatch_contexts d
         JOIN worker_dispatches w ON w.dispatch_id = d.id
         WHERE d.run_id = ? AND d.status IN ('pending', 'dispatched')
           AND w.state = 'starting' AND w.agent_terminal_handle IS NULL`
      )
      .all(run.id) as DispatchContextRow[]
    for (const row of rows) {
      if (this.db.getTask(row.task_id)?.status !== 'dispatched') {
        continue
      }
      this.db.markWorkerStartUnknown(
        row.id,
        'start_unknown',
        'Orca restarted before the worker launch was observed.'
      )
      recordAutomaticRunEvent.call(this.db, {
        runId: run.id,
        kind: 'launch_unknown',
        eventKey: `launch_unknown:${row.id}`,
        taskId: row.task_id,
        dispatchId: row.id,
        payload: { reason: 'runtime_restarted_before_observation' }
      })
    }
  }
}

function eventDetail(
  payload: Record<string, unknown>,
  report: Record<string, unknown>,
  kind: string
): string {
  if (typeof payload.error === 'string') {
    return payload.error
  }
  if (typeof payload.reason === 'string') {
    return payload.reason
  }
  return typeof report.summary === 'string' ? report.summary : kind
}
