import type { AutomaticRunWakeRow, DecisionGateRow, TaskRow } from '../../types'
import { OrchestrationError } from '../../orchestration-error'
import { generateId } from '../generated-id'
import type { OrchestrationDb } from '../orchestration-db'

export type AutomaticTaskDeliveryInput = {
  taskId: string
  runId: string
  dispatchId?: string | null
  outcome: 'succeeded' | 'failed'
  summary: string
  evidence: string[]
  handoff?: string
  reviewVerdict?: 'approved' | 'changes_requested'
  codeVersion?: string | null
}

// A coordinator often answers "Approved, minor notes"; the leading verdict is the decision.
const REVIEW_RESOLUTION_APPROVED = /^(approved|approve|lgtm)\b/

export function recordAutomaticTaskDelivery(
  this: OrchestrationDb,
  delivery: AutomaticTaskDeliveryInput
): void {
  if (!this.isAutomaticRun(delivery.runId)) {
    return
  }
  const evidence = JSON.stringify(delivery.evidence)
  this.db
    .prepare(
      `INSERT OR IGNORE INTO task_deliveries (
         task_id, run_id, dispatch_id, outcome, summary, evidence, handoff,
         review_verdict, code_version
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .run(
      delivery.taskId,
      delivery.runId,
      delivery.dispatchId ?? null,
      delivery.outcome,
      delivery.summary,
      evidence,
      delivery.handoff ?? null,
      delivery.reviewVerdict ?? null,
      delivery.codeVersion ?? null
    )
  const stored = this.db
    .prepare('SELECT * FROM task_deliveries WHERE task_id = ?')
    .get(delivery.taskId) as Record<string, unknown> | undefined
  if (!stored) {
    return
  }
  const json = JSON.stringify({
    outcome: stored.outcome,
    summary: stored.summary,
    evidence: JSON.parse(String(stored.evidence)),
    ...(stored.handoff ? { handoff: stored.handoff } : {}),
    ...(stored.review_verdict ? { reviewVerdict: stored.review_verdict } : {}),
    ...(stored.dispatch_id ? { dispatchId: stored.dispatch_id } : {}),
    ...(stored.code_version ? { codeVersion: stored.code_version } : {}),
    completedAt: stored.created_at
  })
  this.db.prepare('UPDATE tasks SET delivery = ? WHERE id = ?').run(json, delivery.taskId)
}

export function getTaskDeliveryRow(
  this: OrchestrationDb,
  taskId: string
): Record<string, unknown> | undefined {
  return this.db.prepare('SELECT * FROM task_deliveries WHERE task_id = ?').get(taskId) as
    | Record<string, unknown>
    | undefined
}

export function createAutomaticRunGate(
  this: OrchestrationDb,
  gate: { runId: string; taskId: string; question: string; options?: string[] }
): DecisionGateRow {
  const task = this.getTask(gate.taskId)
  if (!task || task.run_id !== gate.runId) {
    throw new OrchestrationError(
      'task_not_found',
      `Task ${gate.taskId} is not in Run ${gate.runId}.`
    )
  }
  const existing = this.db
    .prepare("SELECT * FROM decision_gates WHERE task_id = ? AND status = 'pending'")
    .get(gate.taskId) as DecisionGateRow | undefined
  if (existing) {
    return existing
  }
  const id = generateId('gate')
  this.db
    .prepare(
      'INSERT INTO decision_gates (id, run_id, task_id, question, options) VALUES (?, ?, ?, ?, ?)'
    )
    .run(id, gate.runId, gate.taskId, gate.question, JSON.stringify(gate.options ?? []))
  return this.db.prepare('SELECT * FROM decision_gates WHERE id = ?').get(id) as DecisionGateRow
}

export function listPendingGatesForRun(this: OrchestrationDb, runId: string): DecisionGateRow[] {
  return this.db
    .prepare(
      "SELECT * FROM decision_gates WHERE run_id = ? AND status = 'pending' ORDER BY created_at"
    )
    .all(runId) as DecisionGateRow[]
}

export function isApprovedGateResolution(resolution: string): boolean {
  return REVIEW_RESOLUTION_APPROVED.test(resolution.trim().toLowerCase())
}

export function recordAutomaticWake(
  this: OrchestrationDb,
  wake: { runId: string; eventId: string; eventKey: string; reason: string }
): AutomaticRunWakeRow {
  const existing = this.db
    .prepare('SELECT * FROM automatic_run_wakes WHERE event_key = ?')
    .get(wake.eventKey) as AutomaticRunWakeRow | undefined
  if (existing) {
    return existing
  }
  const id = generateId('awake')
  this.db
    .prepare(
      `INSERT INTO automatic_run_wakes (id, run_id, event_id, reason, event_key, status)
       VALUES (?, ?, ?, ?, ?, 'queued')`
    )
    .run(id, wake.runId, wake.eventId, wake.reason, wake.eventKey)
  return this.db
    .prepare('SELECT * FROM automatic_run_wakes WHERE id = ?')
    .get(id) as AutomaticRunWakeRow
}

export function markAutomaticWakeDelivered(
  this: OrchestrationDb,
  wakeId: string,
  messageId: string | null
): void {
  this.db
    .prepare(
      `UPDATE automatic_run_wakes
       SET status = 'delivered', message_id = ?, delivered_at = datetime('now')
       WHERE id = ? AND status = 'queued'`
    )
    .run(messageId, wakeId)
}

export function listQueuedAutomaticWakes(
  this: OrchestrationDb,
  runId: string
): AutomaticRunWakeRow[] {
  return this.db
    .prepare("SELECT * FROM automatic_run_wakes WHERE run_id = ? AND status = 'queued'")
    .all(runId) as AutomaticRunWakeRow[]
}

export function hasUnreadAutomaticWake(this: OrchestrationDb, runId: string): boolean {
  return Boolean(
    this.db
      .prepare(
        `SELECT 1 FROM messages
         WHERE run_id = ? AND read = 0 AND delivery_contract <> 'audit_only'
           AND json_extract(payload, '$.automaticRunWake') = 1
         LIMIT 1`
      )
      .get(runId)
  )
}

/** Manual starts in an automatic Run share its pause, capacity and decision-gate guarantees. */
export function assertAutomaticRunAdmitsLaunch(
  this: OrchestrationDb,
  runId: string,
  taskId: string
): void {
  const run = this.getRun(runId)
  if (!run || run.execution_mode !== 'automatic') {
    return
  }
  if (run.execution_state !== 'running') {
    throw new OrchestrationError(
      'run_not_running',
      `Run ${runId} is ${run.execution_state ?? 'not running'}; automatic launches only start while it is running.`
    )
  }
  const active = this.db
    .prepare(
      "SELECT COUNT(*) AS count FROM dispatch_contexts WHERE run_id = ? AND status IN ('pending', 'dispatched')"
    )
    .get(runId) as { count: number }
  if (active.count >= run.max_parallel) {
    throw new OrchestrationError(
      'capacity_exceeded',
      `Run ${runId} already has ${active.count} active workers; its parallel limit is ${run.max_parallel}.`
    )
  }
  const task = this.getTask(taskId)
  if (!task) {
    return
  }
  const gate = this.listPendingGatesForRun(runId).find((row) =>
    coveredTaskIds(this, task).has(row.task_id)
  )
  if (gate) {
    throw new OrchestrationError(
      'decision_gate_open',
      `Run ${runId} has an unresolved decision gate on Task ${gate.task_id}; resolve it before starting ${taskId}.`
    )
  }
}

function coveredTaskIds(db: OrchestrationDb, task: TaskRow): Set<string> {
  const covered = new Set<string>([task.id])
  let frontier = [task.id]
  while (frontier.length > 0) {
    const next: string[] = []
    for (const id of frontier) {
      const row = db.getTask(id)
      if (!row) {
        continue
      }
      for (const depId of JSON.parse(row.deps) as string[]) {
        if (!covered.has(depId)) {
          covered.add(depId)
          next.push(depId)
        }
      }
    }
    frontier = next
  }
  return covered
}

export type AutomaticRunActivityStoreMethods = {
  recordAutomaticTaskDelivery: typeof recordAutomaticTaskDelivery
  getTaskDeliveryRow: typeof getTaskDeliveryRow
  createAutomaticRunGate: typeof createAutomaticRunGate
  listPendingGatesForRun: typeof listPendingGatesForRun
  isApprovedGateResolution: typeof isApprovedGateResolution
  recordAutomaticWake: typeof recordAutomaticWake
  markAutomaticWakeDelivered: typeof markAutomaticWakeDelivered
  listQueuedAutomaticWakes: typeof listQueuedAutomaticWakes
  hasUnreadAutomaticWake: typeof hasUnreadAutomaticWake
  assertAutomaticRunAdmitsLaunch: typeof assertAutomaticRunAdmitsLaunch
}

export function attachAutomaticRunActivityStore(ctor: { prototype: object }): void {
  Object.assign(ctor.prototype, {
    recordAutomaticTaskDelivery,
    getTaskDeliveryRow,
    createAutomaticRunGate,
    listPendingGatesForRun,
    isApprovedGateResolution,
    recordAutomaticWake,
    markAutomaticWakeDelivered,
    listQueuedAutomaticWakes,
    hasUnreadAutomaticWake,
    assertAutomaticRunAdmitsLaunch
  })
}
