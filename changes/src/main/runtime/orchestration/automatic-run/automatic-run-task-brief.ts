import type { OrchestrationDb } from '../db'
import type { TaskRow } from '../types'
import { deliveryOfTask } from '../../../../shared/orchestration-workflow'

const MAX_BRIEF_CHARS = 8000

/**
 * Deterministic handoff package: the worker gets its own spec plus direct dependency
 * deliveries and accepted decisions, never the whole chat or terminal transcript.
 */
export function automaticTaskBrief(db: OrchestrationDb, task: TaskRow): string {
  const deps = (JSON.parse(task.deps) as string[])
    .map((id) => db.getTask(id))
    .filter((dep): dep is TaskRow => Boolean(dep))
  if (deps.length === 0) {
    return task.spec
  }
  const sections = ['--- AUTOMATIC RUN CONTEXT (from durable records) ---']
  for (const dep of deps) {
    const delivery = deliveryOfTask(dep)
    const label = dep.task_title ?? dep.display_name ?? dep.id
    sections.push(`Dependency: ${label} [${dep.status}]`)
    if (delivery) {
      if (delivery.summary) {
        sections.push(`  Result: ${delivery.summary}`)
      }
      if (delivery.evidence.length > 0) {
        sections.push(`  Evidence: ${delivery.evidence.join(', ')}`)
      }
      if (delivery.handoff) {
        sections.push(`  Handoff: ${delivery.handoff}`)
      }
    }
    if (dep.resolved_worktree_id) {
      sections.push(`  Workspace: ${dep.resolved_worktree_id}`)
    }
    for (const gate of db.listGates({ taskId: dep.id, status: 'resolved' })) {
      if (gate.resolution) {
        sections.push(`  Decision: ${gate.question} -> ${gate.resolution}`)
      }
    }
  }
  sections.push(
    'Use the dependency results above as the starting point; do not repeat completed work.'
  )
  const suffix = `\n\n${sections.join('\n')}`
  return `${task.spec.slice(0, Math.max(0, MAX_BRIEF_CHARS - suffix.length))}${suffix}`
}
