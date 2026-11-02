import type { RunExecutionOutcome, RunRow } from '../types'
import { deliveryOfTask } from '../../../../shared/orchestration-workflow'
import type { OrchestrationDb } from '../db'
import type { AutomaticRunHost } from './automatic-run-executor'
import { recordAutomaticWake } from '../db/automatic-runs/automatic-run-activity-store'

/** A failed branch waits for a coordinator decision; only an all-completed Run settles itself. */
export function settleIfFinished(
  db: OrchestrationDb,
  host: AutomaticRunHost,
  run: RunRow,
  activeCount: number
): void {
  if (run.execution_state !== 'running') {
    return
  }
  if (db.listPendingAutomaticRunEvents(run.id).length > 0 || activeCount > 0) {
    return
  }
  if (db.listPendingGatesForRun(run.id).length > 0) {
    return
  }
  const tasks = db.listTasks({ runId: run.id })
  if (tasks.length === 0 || !tasks.every((task) => task.status === 'completed')) {
    return
  }
  settleRun(db, host, run, 'completed')
}

export function settleRun(
  db: OrchestrationDb,
  host: AutomaticRunHost,
  run: RunRow,
  outcome: RunExecutionOutcome
): void {
  const current = db.getRun(run.id)
  if (!current) {
    return
  }
  let created = false
  db.db.exec('BEGIN IMMEDIATE')
  try {
    if (current.execution_state === 'settled') {
      if (!current.final_report_delivered_at) {
        created = writeFinalReport(db, run.id)
      }
      db.db.exec('COMMIT')
    } else {
      if (
        db.setRunExecutionState(run.id, 'settled', { outcome, settledAt: new Date().toISOString() })
      ) {
        created = writeFinalReport(db, run.id)
      }
      db.db.exec('COMMIT')
    }
  } catch (error) {
    db.db.exec('ROLLBACK')
    throw error
  }
  if (created) {
    host.notifyRun(run.id)
  }
}

/** Rebuild a report lost between marking the Run settled and delivering its wake. */
export function recoverFinalReports(db: OrchestrationDb, host: AutomaticRunHost): void {
  for (const run of db.listAutomaticRunsAwaitingFinalReport()) {
    let created = false
    db.db.exec('BEGIN IMMEDIATE')
    try {
      created = writeFinalReport(db, run.id)
      db.db.exec('COMMIT')
    } catch (error) {
      db.db.exec('ROLLBACK')
      throw error
    }
    if (created) {
      host.notifyRun(run.id)
    }
  }
}

function writeFinalReport(db: OrchestrationDb, runId: string): boolean {
  const current = db.getRun(runId)
  if (!current || current.final_report_delivered_at) {
    return false
  }
  const tasks = db.listTasks({ runId })
  const completed = tasks.filter((task) => task.status === 'completed').length
  const failed = tasks.filter((task) => task.status === 'failed').length
  const pending = tasks.length - completed - failed
  const outcome = current.execution_outcome ?? 'failed'
  const body = [
    `Automatic Run ${runId} settled: ${outcome}.`,
    `Tasks: ${completed} completed, ${failed} failed, ${pending} not completed.`,
    ...tasks.map((task) => {
      const delivery = deliveryOfTask(task)
      const label = task.task_title ?? task.display_name ?? task.id
      return `- ${label} [${task.status}]${delivery ? `: ${delivery.summary}` : ''}`
    })
  ].join('\n')
  const wake = recordAutomaticWake.call(db, {
    runId,
    eventId: 'final-report',
    eventKey: `settled:${runId}`,
    reason: body
  })
  if (wake.status === 'delivered' && wake.message_id) {
    if (db.getMessageById(wake.message_id)) {
      db.markRunFinalReportDelivered(runId, new Date().toISOString())
      return false
    }
    // The message was removed with older rows; re-open the wake so the report can be delivered.
    db.db
      .prepare("UPDATE automatic_run_wakes SET status = 'queued', message_id = NULL WHERE id = ?")
      .run(wake.id)
  }
  const message = db.insertMessage({
    from: 'orca:auto',
    to: `run:${runId}`,
    subject: `Automatic Run ${runId} final report`,
    body,
    type: 'status',
    priority: 'normal',
    runId,
    payload: JSON.stringify({ automaticRunWake: true, runId, finalReport: true })
  })
  db.markAutomaticWakeDelivered(wake.id, message.id)
  db.markRunFinalReportDelivered(runId, message.created_at)
  return true
}
