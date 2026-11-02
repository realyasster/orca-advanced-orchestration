import type { OrchestrationDb } from '../orchestration-db'
import type { TaskRow, WorkerReportOutcome } from '../../types'
import { recordAutomaticTaskDelivery } from './automatic-run-activity-store'

/** Persist the worker completion contract, then the Task's durable delivery projection. */
export function recordAutomaticWorkerDelivery(
  db: OrchestrationDb,
  task: TaskRow,
  dispatchId: string,
  outcome: WorkerReportOutcome,
  result: string
): void {
  const report = parseWorkerResult(result)
  recordAutomaticTaskDelivery.call(db, {
    taskId: task.id,
    runId: task.run_id,
    dispatchId,
    outcome,
    summary: report.summary,
    evidence: report.evidence,
    ...(report.handoff ? { handoff: report.handoff } : {}),
    ...(report.reviewVerdict ? { reviewVerdict: report.reviewVerdict } : {}),
    codeVersion: task.code_version
  })
}

function parseWorkerResult(result: string): {
  summary: string
  evidence: string[]
  handoff?: string
  reviewVerdict?: 'approved' | 'changes_requested'
} {
  try {
    const parsed: unknown = JSON.parse(result)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { summary: '', evidence: [] }
    }
    const record = parsed as Record<string, unknown>
    return {
      summary: typeof record.summary === 'string' ? record.summary : '',
      evidence: Array.isArray(record.evidence)
        ? record.evidence.filter((item): item is string => typeof item === 'string')
        : [],
      ...(typeof record.handoff === 'string' ? { handoff: record.handoff } : {}),
      ...(record.reviewVerdict === 'approved' || record.reviewVerdict === 'changes_requested'
        ? { reviewVerdict: record.reviewVerdict }
        : {})
    }
  } catch {
    return { summary: '', evidence: [] }
  }
}
