import type { OrchestrationDb } from '../../../../orchestration/db'
import type { DecisionGateRow, RunRow, TaskRow } from '../../../../orchestration/types'
import { deliveryOfTask } from '../../../../../../shared/orchestration-workflow'

type JoinedTask = TaskRow & { assignee_handle: string | null; dispatch_id: string | null }

/** Durable waiting state and delivery evidence for the agent-facing task list. */
export function projectAutomaticTaskRows(
  db: OrchestrationDb,
  run: RunRow,
  rows: JoinedTask[],
  gates: DecisionGateRow[]
): (Omit<JoinedTask, 'assignee_handle' | 'dispatch_id'> & {
  assignee_handle?: string | null
  dispatch_id?: string | null
  wait_reason: string
  delivery_summary: string | null
  delivery_evidence: string[] | null
  review_verdict: string | null
})[] {
  const gateByTask = new Map(gates.map((gate) => [gate.task_id, gate]))
  return rows.map((row) => {
    const { assignee_handle, dispatch_id, ...base } = row
    const delivery = base.delivery ? deliveryOfTask({ delivery: base.delivery }) : null
    const deps = safeJsonArray(base.deps)
    const waitReason = (() => {
      if (base.status === 'dispatched') {
        return 'worker_running'
      }
      if (gateByTask.has(base.id)) {
        return `decision_gate:${gateByTask.get(base.id)?.id}`
      }
      if (base.status === 'failed') {
        return 'worker_failed'
      }
      if (base.status === 'blocked') {
        return 'blocked'
      }
      if (
        base.status === 'ready' &&
        deps.some((depId) => db.getTask(depId)?.status !== 'completed')
      ) {
        return 'dependencies'
      }
      if (base.status === 'ready' && run.execution_state !== 'running') {
        return `run_${run.execution_state ?? 'manual'}`
      }
      if (base.status === 'ready') {
        return 'ready'
      }
      return 'dependencies'
    })()
    return {
      ...base,
      wait_reason: waitReason,
      delivery_summary: delivery?.summary ?? null,
      delivery_evidence: delivery?.evidence ?? null,
      review_verdict: delivery?.reviewVerdict ?? null,
      ...(base.status === 'dispatched' ? { assignee_handle, dispatch_id } : {})
    }
  })
}

function safeJsonArray(value: string): string[] {
  try {
    const parsed: unknown = JSON.parse(value)
    return Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === 'string')
      : []
  } catch {
    return []
  }
}
