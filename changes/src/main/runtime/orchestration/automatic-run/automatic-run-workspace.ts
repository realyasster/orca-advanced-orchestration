import type { RunRow, TaskRow } from '../types'
import type { OrchestrationTaskExecutionOptions } from '../../../../shared/orchestration-workflow'
import type { OrchestrationDb } from '../db'

export type WorkspaceTarget = { selector: string | undefined; workspaceKey: string | null } | 'wait'

export function dependencyClosure(db: OrchestrationDb, task: TaskRow): Set<string> {
  const closure = new Set<string>()
  const queue = [task.id]
  while (queue.length > 0) {
    const id = queue.shift() as string
    const row = db.getTask(id)
    if (!row) {
      continue
    }
    for (const depId of JSON.parse(row.deps) as string[]) {
      if (!closure.has(depId)) {
        closure.add(depId)
        queue.push(depId)
      }
    }
  }
  return closure
}

export function resolveWorkspace(
  db: OrchestrationDb,
  run: RunRow,
  task: TaskRow,
  options: OrchestrationTaskExecutionOptions,
  simultaneousWriteBatch: boolean
): WorkspaceTarget {
  // A review must see the implementation's exact code version.
  if (!options.workspaceFrom && task.review_of_task_id) {
    const reviewed = db.getTask(task.review_of_task_id)
    if (reviewed?.resolved_worktree_id) {
      return {
        selector: `id:${reviewed.resolved_worktree_id}`,
        workspaceKey: reviewed.resolved_worktree_id
      }
    }
  }
  if (options.workspaceFrom) {
    const source = db.db
      .prepare('SELECT * FROM tasks WHERE run_id = ? AND source_key = ?')
      .get(run.id, options.workspaceFrom) as TaskRow | undefined
    if (!source?.resolved_worktree_id) {
      return 'wait'
    }
    return {
      selector: `id:${source.resolved_worktree_id}`,
      workspaceKey: source.resolved_worktree_id
    }
  }
  if (options.worktree?.startsWith('id:')) {
    return { selector: options.worktree, workspaceKey: options.worktree.slice(3) }
  }
  if (options.worktree === 'new-child' || options.worktree === 'new-top-level') {
    return { selector: options.worktree, workspaceKey: null }
  }
  if (options.worktree === 'current' || !options.worktree) {
    if (simultaneousWriteBatch && options.workspaceUsage === 'write') {
      return { selector: 'new-child', workspaceKey: null }
    }
    return {
      selector: run.workspace_id ? `id:${run.workspace_id}` : undefined,
      workspaceKey: run.workspace_id
    }
  }
  return { selector: options.worktree, workspaceKey: null }
}

/** A write excludes every worker in the workspace; a read only waits for a writer. */
export function workspaceConflicts(
  usage: 'read' | 'write',
  workspaceKey: string,
  activeWorkspaces: Set<string>,
  activeWriteWorkspaces: Set<string>
): boolean {
  return usage === 'write'
    ? activeWorkspaces.has(workspaceKey)
    : activeWriteWorkspaces.has(workspaceKey)
}
