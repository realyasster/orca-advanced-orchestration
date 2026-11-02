import type { AutomaticRunEventRow, RunRow, TaskRow } from '../types'
import type { OrchestrationDb } from '../db'
import { createAutomaticRunGate } from '../db/automatic-runs/automatic-run-activity-store'
import { markAutomaticRunEventProcessed } from '../db/automatic-runs/automatic-run-store'

/**
 * Failure of an event handler must park the branch and wake the coordinator.
 * It runs after the event transaction rolled back, in its own transaction.
 */
export function handleAutomaticEventFailure(
  db: OrchestrationDb,
  run: RunRow,
  event: AutomaticRunEventRow,
  error: unknown
): void {
  const reason =
    `Automatic executor could not process ${event.kind} for ` +
    `${event.task_id ?? 'its Task'}: ${error instanceof Error ? error.message : String(error)}`
  db.db.exec('BEGIN IMMEDIATE')
  try {
    const task = event.task_id ? db.getTask(event.task_id) : undefined
    if (task) {
      ensureWaitingBranch(db, run.id, task, reason)
    }
    db.recordAutomaticWake({
      runId: run.id,
      eventId: event.id,
      eventKey: `event_failed:${event.id}`,
      reason
    })
    markAutomaticRunEventProcessed.call(db, event.id, 'failed')
    db.db.exec('COMMIT')
  } catch (failure) {
    db.db.exec('ROLLBACK')
    console.warn('[automatic-run] event failure fallback failed', run.id, event.kind, failure)
    recordFailureWakeOnly(db, run.id, event, reason)
  }
}

function ensureWaitingBranch(
  db: OrchestrationDb,
  runId: string,
  task: TaskRow,
  reason: string
): void {
  db.db.exec('SAVEPOINT executor_event_wait')
  try {
    createAutomaticRunGate.call(db, {
      runId,
      taskId: task.id,
      question: `${reason} Inspect the Task and resolve this gate to continue.`,
      options: ['approved', 'changes_requested']
    })
    if (task.status === 'pending' || task.status === 'ready') {
      db.db
        .prepare(
          "UPDATE tasks SET status = 'blocked' WHERE id = ? AND status IN ('pending', 'ready')"
        )
        .run(task.id)
    }
    db.db.exec('RELEASE executor_event_wait')
  } catch {
    db.db.exec('ROLLBACK TO executor_event_wait')
    db.db.exec('RELEASE executor_event_wait')
    // Last resort: hold the reviewed branch even if the gate row could not be written.
    const reviewedTaskId = task.review_of_task_id ?? task.id
    for (const candidate of db.listTasks({ runId })) {
      if (candidate.status !== 'pending' && candidate.status !== 'ready') {
        continue
      }
      const deps = JSON.parse(candidate.deps) as string[]
      if (
        deps.includes(task.id) ||
        deps.includes(reviewedTaskId) ||
        candidate.review_of_task_id === reviewedTaskId
      ) {
        db.db.prepare("UPDATE tasks SET status = 'blocked' WHERE id = ?").run(candidate.id)
      }
    }
  }
}

function recordFailureWakeOnly(
  db: OrchestrationDb,
  runId: string,
  event: AutomaticRunEventRow,
  reason: string
): void {
  db.db.exec('BEGIN IMMEDIATE')
  try {
    db.recordAutomaticWake({
      runId,
      eventId: event.id,
      eventKey: `event_failed:${event.id}`,
      reason
    })
    markAutomaticRunEventProcessed.call(db, event.id, 'failed')
    db.db.exec('COMMIT')
  } catch (failure) {
    db.db.exec('ROLLBACK')
    console.error('[automatic-run] could not record event failure wake', runId, event.id, failure)
  }
}
