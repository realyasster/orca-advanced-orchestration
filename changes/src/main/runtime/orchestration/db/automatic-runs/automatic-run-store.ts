import type {
  AutomaticRunEventRow,
  RunExecutionOutcome,
  RunExecutionState,
  RunRow
} from '../../types'
import { generateId } from '../generated-id'
import type { OrchestrationDb } from '../orchestration-db'

export type AutomaticRunEventInput = {
  runId: string
  kind: string
  eventKey: string
  taskId?: string | null
  dispatchId?: string | null
  payload?: unknown
}

export function recordAutomaticRunEvent(
  this: OrchestrationDb,
  event: AutomaticRunEventInput
): void {
  const mode = this.db.prepare('SELECT execution_mode FROM runs WHERE id = ?').get(event.runId) as
    | { execution_mode: string }
    | undefined
  if (mode?.execution_mode !== 'automatic') {
    return
  }
  this.db
    .prepare(
      `INSERT OR IGNORE INTO automatic_run_events (
         id, run_id, task_id, dispatch_id, kind, event_key, payload, state
       ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')`
    )
    .run(
      generateId('aevent'),
      event.runId,
      event.taskId ?? null,
      event.dispatchId ?? null,
      event.kind,
      event.eventKey,
      JSON.stringify(event.payload ?? {})
    )
}

/** Called inside a lifecycle transaction; an automatic Run's mutation and its outbox event commit together. */
export function recordAutomaticRunEventForRun(
  db: OrchestrationDb,
  runId: string,
  event: Omit<AutomaticRunEventInput, 'runId'>
): void {
  recordAutomaticRunEvent.call(db, { ...event, runId })
}

export function isAutomaticRun(this: OrchestrationDb, runId: string): boolean {
  return (
    (
      this.db.prepare('SELECT execution_mode FROM runs WHERE id = ?').get(runId) as
        | { execution_mode: string }
        | undefined
    )?.execution_mode === 'automatic'
  )
}

export function listAutomaticRunsForRecovery(this: OrchestrationDb): RunRow[] {
  return this.db
    .prepare(
      `SELECT * FROM runs
       WHERE execution_mode = 'automatic'
         AND execution_state IN ('preparing', 'running', 'cancelling')
       ORDER BY created_at`
    )
    .all() as RunRow[]
}

export function listAutomaticRunsAwaitingFinalReport(this: OrchestrationDb): RunRow[] {
  return this.db
    .prepare(
      `SELECT * FROM runs
       WHERE execution_mode = 'automatic' AND execution_state = 'settled'
         AND final_report_delivered_at IS NULL
       ORDER BY settled_at, created_at`
    )
    .all() as RunRow[]
}

export function setRunExecutionState(
  this: OrchestrationDb,
  runId: string,
  state: RunExecutionState,
  extra: {
    outcome?: RunExecutionOutcome | null
    pauseReason?: string | null
    cancelReason?: string | null
    settledAt?: string | null
    finalReportDeliveredAt?: string | null
  } = {}
): boolean {
  const result = this.db
    .prepare(
      `UPDATE runs SET execution_state = ?, execution_outcome = ?,
         pause_reason = ?, cancel_reason = ?, settled_at = ?,
         final_report_delivered_at = COALESCE(?, final_report_delivered_at),
         updated_at = datetime('now')
       WHERE id = ? AND execution_mode = 'automatic' AND execution_state <> 'settled'`
    )
    .run(
      state,
      extra.outcome ?? null,
      extra.pauseReason ?? null,
      extra.cancelReason ?? null,
      extra.settledAt ?? null,
      extra.finalReportDeliveredAt ?? null,
      runId
    )
  return result.changes === 1
}

export function markRunFinalReportDelivered(
  this: OrchestrationDb,
  runId: string,
  deliveredAt: string
): void {
  this.db
    .prepare(
      `UPDATE runs SET final_report_delivered_at = COALESCE(final_report_delivered_at, ?),
         updated_at = datetime('now')
       WHERE id = ?`
    )
    .run(deliveredAt, runId)
}

export function listPendingAutomaticRunEvents(
  this: OrchestrationDb,
  runId: string,
  limit = 100
): AutomaticRunEventRow[] {
  return this.db
    .prepare(
      `SELECT * FROM automatic_run_events
       WHERE run_id = ? AND state = 'pending'
       ORDER BY created_at, rowid LIMIT ?`
    )
    .all(runId, limit) as AutomaticRunEventRow[]
}

export function markAutomaticRunEventProcessed(
  this: OrchestrationDb,
  eventId: string,
  state: 'processed' | 'failed' = 'processed'
): void {
  this.db
    .prepare(
      `UPDATE automatic_run_events
       SET state = ?, attempts = attempts + 1, processed_at = datetime('now')
       WHERE id = ? AND state = 'pending'`
    )
    .run(state, eventId)
}

export type AutomaticRunStoreMethods = {
  isAutomaticRun: typeof isAutomaticRun
  listAutomaticRunsForRecovery: typeof listAutomaticRunsForRecovery
  listAutomaticRunsAwaitingFinalReport: typeof listAutomaticRunsAwaitingFinalReport
  setRunExecutionState: typeof setRunExecutionState
  markRunFinalReportDelivered: typeof markRunFinalReportDelivered
  recordAutomaticRunEvent: typeof recordAutomaticRunEvent
  listPendingAutomaticRunEvents: typeof listPendingAutomaticRunEvents
  markAutomaticRunEventProcessed: typeof markAutomaticRunEventProcessed
}

export function attachAutomaticRunStore(ctor: { prototype: object }): void {
  Object.assign(ctor.prototype, {
    isAutomaticRun,
    listAutomaticRunsForRecovery,
    listAutomaticRunsAwaitingFinalReport,
    setRunExecutionState,
    markRunFinalReportDelivered,
    recordAutomaticRunEvent,
    listPendingAutomaticRunEvents,
    markAutomaticRunEventProcessed
  })
}
