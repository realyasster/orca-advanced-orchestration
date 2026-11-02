import type { AutomaticRunEventRow, RunRow, TaskRow } from '../types'
import {
  deliveryOfTask,
  executionOptionsOfTask,
  type OrchestrationTaskExecutionOptions
} from '../../../../shared/orchestration-workflow'
import { buildOrchestrationTaskDisplayMetadata } from '../../../../shared/orchestration-task-display'
import {
  createAutomaticRunGate,
  isApprovedGateResolution
} from '../db/automatic-runs/automatic-run-activity-store'
import { recordAutomaticRunEvent } from '../db/automatic-runs/automatic-run-store'
import type { OrchestrationDb } from '../db'

export type AttentionEvent = {
  eventId: string
  eventKey: string
  reason: string
}

export function afterTaskCompleted(db: OrchestrationDb, runId: string, task?: TaskRow): void {
  if (!task) {
    return
  }
  if (task.review_role === 'review' || task.needs_coordinator_review === 1) {
    openReviewGate(db, runId, task)
  }
}

function openReviewGate(db: OrchestrationDb, runId: string, task: TaskRow): void {
  const reviewed = task.review_of_task_id ? db.getTask(task.review_of_task_id) : undefined
  const target = reviewed ?? task
  const label =
    buildOrchestrationTaskDisplayMetadata({
      spec: target.spec,
      taskTitle: target.task_title,
      displayName: target.display_name
    }).taskTitle || target.id
  const verdict = deliveryOfTask(task)?.reviewVerdict
  const gate = createAutomaticRunGate.call(db, {
    runId,
    taskId: task.id,
    question:
      task.review_role === 'review'
        ? `Review the result of "${label}" and answer approved or changes_requested.${verdict ? ` The reviewer reported ${verdict}.` : ''}`
        : `Review the completed Task "${label}" and answer approved or changes_requested.`,
    options: ['approved', 'changes_requested']
  })
  recordAutomaticRunEvent.call(db, {
    runId,
    kind: 'gate_opened',
    eventKey: `gate_opened:${gate.id}`,
    taskId: task.id,
    dispatchId: null,
    payload: { gateId: gate.id, question: gate.question }
  })
}

export function afterGateResolved(
  db: OrchestrationDb,
  runId: string,
  event: AutomaticRunEventRow
): void {
  const payload = parseJson(event.payload)
  const gateId = typeof payload.gateId === 'string' ? payload.gateId : null
  const resolution = typeof payload.resolution === 'string' ? payload.resolution : ''
  if (!gateId || isApprovedGateResolution(resolution)) {
    return
  }
  const gate = db.getGate(gateId)
  if (!gate) {
    return
  }
  const task = db.getTask(gate.task_id)
  if (!task || task.correction_round >= 2) {
    createAutomaticRunGate.call(db, {
      runId,
      taskId: task?.id ?? gate.task_id,
      question: `Correction limit reached for "${task?.task_title ?? gate.task_id}". Resolve manually with approved or changes_requested, or edit the workflow.`,
      options: ['approved', 'changes_requested']
    })
    return
  }
  const round = task.correction_round + 1
  const reviewedTask =
    task.review_role === 'review' && task.review_of_task_id
      ? db.getTask(task.review_of_task_id)
      : task
  const reviewSource = task.review_role === 'review' ? task : undefined
  const correction = db.createTask({
    runId,
    spec: `Address the review findings for "${reviewedTask?.task_title ?? task.task_title ?? task.id}":\n\n${resolution}`,
    taskTitle: `Correction ${round}: ${reviewedTask?.task_title ?? task.task_title ?? task.id}`,
    deps: [task.id],
    autoOptions: JSON.stringify(
      executionOptionsOfTask(task) satisfies OrchestrationTaskExecutionOptions
    ),
    reviewRole: 'correction',
    reviewOfTaskId: reviewedTask?.id ?? task.id,
    correctionRound: round,
    needsCoordinatorReview: !reviewSource
  })
  db.db
    .prepare('UPDATE tasks SET resolved_worktree_id = ? WHERE id = ?')
    .run(task.resolved_worktree_id, correction.id)
  if (reviewSource) {
    const reReview = db.createTask({
      runId,
      spec: reviewSource.spec,
      taskTitle: `Re-review ${round}: ${reviewedTask?.task_title ?? reviewSource.id}`,
      deps: [correction.id],
      autoOptions: reviewSource.auto_options,
      reviewRole: 'review',
      reviewOfTaskId: reviewedTask?.id ?? task.id,
      correctionRound: round
    })
    db.db
      .prepare('UPDATE tasks SET resolved_worktree_id = ? WHERE id = ?')
      .run(task.resolved_worktree_id, reReview.id)
  }
}

export function pendingGateAttention(db: OrchestrationDb, run: RunRow): AttentionEvent[] {
  return db
    .listPendingGatesForRun(run.id)
    .filter(
      (gate) =>
        !db.db
          .prepare('SELECT 1 FROM automatic_run_wakes WHERE event_key = ?')
          .get(`gate_opened:${gate.id}`)
    )
    .map((gate) => ({
      eventId: gate.id,
      eventKey: `gate_opened:${gate.id}`,
      reason: `Decision gate: ${gate.question} (gate ${gate.id})`
    }))
}

export function parseJson(value: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(value)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {}
  } catch {
    return {}
  }
}
