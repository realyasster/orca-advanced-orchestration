import type { DispatchContextRow, RunRow, TaskRow } from '../types'
import { executionOptionsOfTask } from '../../../../shared/orchestration-workflow'
import type { OrchestrationDb } from '../db'
import { recordAutomaticRunEvent } from '../db/automatic-runs/automatic-run-store'
import type { AutomaticLaunchResult, AutomaticRunHost } from './automatic-run-executor'
import { dependencyClosure, resolveWorkspace, workspaceConflicts } from './automatic-run-workspace'

export function activeDispatches(db: OrchestrationDb, runId: string): DispatchContextRow[] {
  return db.db
    .prepare(
      `SELECT * FROM dispatch_contexts
       WHERE run_id = ? AND status IN ('pending', 'dispatched')
       ORDER BY rowid`
    )
    .all(runId) as DispatchContextRow[]
}

export async function launchReadyTasks(
  db: OrchestrationDb,
  host: AutomaticRunHost,
  run: RunRow
): Promise<void> {
  const tasks = db.listTasks({ runId: run.id })
  const active = activeDispatches(db, run.id)
  let slots = run.max_parallel - active.length
  if (slots <= 0) {
    return
  }
  const pendingGateTasks = new Set(db.listPendingGatesForRun(run.id).map((gate) => gate.task_id))
  const activeWorkspaces = new Set<string>()
  const activeWriteWorkspaces = new Set<string>()
  for (const dispatch of active) {
    const task = db.getTask(dispatch.task_id)
    const workspaceKey = task?.resolved_worktree_id
    if (!task || !workspaceKey) {
      continue
    }
    activeWorkspaces.add(workspaceKey)
    if (executionOptionsOfTask(task).workspaceUsage === 'write') {
      activeWriteWorkspaces.add(workspaceKey)
    }
  }
  const ready = tasks.filter((task) => task.status === 'ready')
  const readyWriteCount = ready.filter(
    (task) => executionOptionsOfTask(task).workspaceUsage === 'write'
  ).length
  for (const queuedTask of ready) {
    if (slots <= 0) {
      break
    }
    // A workflow update during this tick must not launch the pre-update spec.
    const freshRun = db.getRun(run.id)
    if (!freshRun || freshRun.workflow_version !== run.workflow_version) {
      break
    }
    const task = db.getTask(queuedTask.id)
    if (!task || task.status !== 'ready' || !canLaunch(db, task, pendingGateTasks, active)) {
      continue
    }
    const options = executionOptionsOfTask(task)
    const target = resolveWorkspace(db, freshRun, task, options, readyWriteCount > 1)
    if (
      target === 'wait' ||
      (target.workspaceKey &&
        workspaceConflicts(
          options.workspaceUsage,
          target.workspaceKey,
          activeWorkspaces,
          activeWriteWorkspaces
        ))
    ) {
      continue
    }
    slots--
    const result = await launchOne(
      db,
      host,
      freshRun,
      task,
      options,
      target.selector,
      target.workspaceKey
    )
    if (result.error || result.failed) {
      slots++
      continue
    }
    if (target.workspaceKey) {
      activeWorkspaces.add(target.workspaceKey)
      if (options.workspaceUsage === 'write') {
        activeWriteWorkspaces.add(target.workspaceKey)
      }
    }
    if (result.worktreeId) {
      db.db
        .prepare('UPDATE tasks SET resolved_worktree_id = ? WHERE id = ?')
        .run(result.worktreeId, task.id)
    }
  }
}

async function launchOne(
  db: OrchestrationDb,
  host: AutomaticRunHost,
  run: RunRow,
  task: TaskRow,
  options: ReturnType<typeof executionOptionsOfTask>,
  worktree: string | undefined,
  workspaceKey: string | null
): Promise<AutomaticLaunchResult & { failed?: boolean }> {
  try {
    const result = await host.launchTask({ run, task, options, worktree, workspaceKey })
    if (!result.error) {
      return result
    }
    await recordLaunchError(db, run, task, result.error)
    return { ...result, failed: true }
  } catch (error) {
    await recordLaunchError(db, run, task, error instanceof Error ? error.message : String(error))
    return { error: 'launch threw', failed: true }
  }
}

async function recordLaunchError(
  db: OrchestrationDb,
  run: RunRow,
  task: TaskRow,
  message: string
): Promise<void> {
  db.db
    .prepare("UPDATE tasks SET status = 'blocked' WHERE id = ? AND status = 'ready'")
    .run(task.id)
  recordAutomaticRunEvent.call(db, {
    runId: run.id,
    kind: 'launch_failed',
    eventKey: `launch_error:${task.id}:${Date.now()}`,
    taskId: task.id,
    payload: { error: message }
  })
}

/** A gate on a review/correction task holds everyone waiting on the Task it reviews. */
function gateBlocksClosure(db: OrchestrationDb, gateTaskId: string, closure: Set<string>): boolean {
  if (closure.has(gateTaskId)) {
    return true
  }
  const gateTask = db.getTask(gateTaskId)
  return Boolean(gateTask?.review_of_task_id && closure.has(gateTask.review_of_task_id))
}

function canLaunch(
  db: OrchestrationDb,
  task: TaskRow,
  pendingGateTasks: Set<string>,
  active: DispatchContextRow[]
): boolean {
  if (active.some((dispatch) => dispatch.task_id === task.id)) {
    return false
  }
  const deps = JSON.parse(task.deps) as string[]
  if (!deps.every((depId) => db.getTask(depId)?.status === 'completed')) {
    return false
  }
  const closure = dependencyClosure(db, task)
  if ([...pendingGateTasks].some((id) => gateBlocksClosure(db, id, closure))) {
    return false
  }
  // A failed review/correction is a waiting branch, not an approval: only completed closes it.
  return !db
    .listTasks({ runId: task.run_id })
    .some(
      (candidate) =>
        candidate.id !== task.id &&
        candidate.review_of_task_id !== null &&
        closure.has(candidate.review_of_task_id) &&
        candidate.status !== 'completed'
    )
}
