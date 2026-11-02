import type { MessageRow } from '../../types'
import type { OrchestrationDb } from '../orchestration-db'
import { recordAutomaticRunEvent } from '../automatic-runs/automatic-run-store'

/** Automatic Runs keep reports as audit rows; the executor decides whether a wake is owed. */
export function markMessageHandled(
  this: OrchestrationDb,
  messageId: string,
  deliveryContract: 'audit_only' | 'current_delivery' = 'audit_only'
): void {
  this.db
    .prepare(
      `UPDATE messages
       SET read = 1, delivered_at = COALESCE(delivered_at, datetime('now')), delivery_contract = ?
       WHERE id = ? AND read = 0`
    )
    .run(deliveryContract, messageId)
}

/** An invalid completion blocks its branch; the executor still owes one decision wake. */
export function recordRejectedCompletionEvent(
  db: OrchestrationDb,
  message: MessageRow,
  code: string,
  reason: string
): void {
  if (message.type !== 'worker_done' || !message.payload) {
    return
  }
  try {
    const parsed: unknown = JSON.parse(message.payload)
    const record =
      parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? (parsed as { taskId?: unknown; dispatchId?: unknown })
        : undefined
    if (typeof record?.taskId !== 'string' || typeof record.dispatchId !== 'string') {
      return
    }
    const task = db.getTask(record.taskId)
    if (!task) {
      return
    }
    recordAutomaticRunEvent.call(db, {
      runId: task.run_id,
      kind: 'invalid_completion',
      eventKey: `rejected:${message.id}`,
      taskId: task.id,
      dispatchId: record.dispatchId,
      payload: { code, reason }
    })
  } catch {
    // Malformed lifecycle payloads are already recorded as a rejection.
  }
}

export type AutomaticMessageRoutingMethods = {
  markMessageHandled: typeof markMessageHandled
}

export function attachAutomaticMessageRouting(ctor: { prototype: object }): void {
  Object.assign(ctor.prototype, { markMessageHandled })
}
