import type { RunRow, TaskRow } from '../../types'
import { OrchestrationError } from '../../orchestration-error'
import { buildOrchestrationTaskDisplayMetadata } from '../../../../../shared/orchestration-task-display'
import type {
  OrchestrationTaskExecutionOptions,
  OrchestrationWorkflowInput
} from '../../../../../shared/orchestration-workflow'
import { validateOrchestrationWorkflow } from '../../../../../shared/orchestration-workflow'
import { generateId } from '../generated-id'
import type { OrchestrationDb } from '../orchestration-db'
import { recordAutomaticRunEvent } from './automatic-run-store'

export type WorkflowApplyResult = {
  run: RunRow
  workflowVersion: number
  created: number
  updated: number
  removed: number
}

/** Apply a validated workflow atomically; started Tasks are never silently rewritten. */
export function applyOrchestrationWorkflow(
  this: OrchestrationDb,
  params: {
    runId: string
    expectedVersion: number
    workflow: OrchestrationWorkflowInput
  }
): WorkflowApplyResult {
  const problems = validateOrchestrationWorkflow(params.workflow)
  if (problems.length > 0) {
    throw new OrchestrationError('invalid_argument', problems.map((p) => p.message).join(' '))
  }
  this.db.exec('BEGIN IMMEDIATE')
  try {
    const run = this.getRun(params.runId)
    if (!run) {
      throw new OrchestrationError('run_not_found', `Run ${params.runId} was not found.`)
    }
    if (run.execution_mode !== 'automatic') {
      throw new OrchestrationError(
        'invalid_argument',
        `Run ${params.runId} is manually operated; create it with --mode automatic to apply a workflow.`
      )
    }
    if (run.execution_state === 'settled') {
      throw new OrchestrationError('run_not_found', `Run ${params.runId} has already settled.`)
    }
    if (run.workflow_version !== params.expectedVersion) {
      throw new OrchestrationError(
        'workflow_version_conflict',
        `Workflow version is ${run.workflow_version}, not ${params.expectedVersion}; reload the Run and retry.`
      )
    }
    const workflowKeys = new Map(params.workflow.tasks.map((task) => [task.key, task]))
    const existing = (
      this.db
        .prepare(
          'SELECT * FROM tasks WHERE run_id = ? AND source_key IS NOT NULL ORDER BY created_at'
        )
        .all(params.runId) as TaskRow[]
    ).map((task) => task)
    const existingByKey = new Map(existing.map((task) => [task.source_key as string, task]))
    const idByKey = new Map<string, string>(
      existing.map((task) => [task.source_key as string, task.id])
    )
    let created = 0
    for (const task of params.workflow.tasks) {
      if (!idByKey.has(task.key)) {
        idByKey.set(task.key, generateId('task'))
        created++
      }
    }
    let updated = 0
    let removed = 0
    const removedIds = new Set<string>()
    for (const task of existing) {
      if (!workflowKeys.has(task.source_key as string)) {
        if (task.status !== 'pending' && task.status !== 'ready') {
          throw new OrchestrationError(
            'workflow_task_started',
            `Task ${task.source_key} has already started (${task.status}); stop it before removing it.`
          )
        }
        removedIds.add(task.id)
        removed++
      }
    }
    for (const task of existing) {
      const requested = workflowKeys.get(task.source_key as string)
      if (!requested || removedIds.has(task.id)) {
        continue
      }
      const desiredDeps = JSON.stringify(requested.dependsOn.map((key) => idByKey.get(key)))
      const nextOptions = JSON.stringify(executionOptionsFor(requested))
      const started = task.status !== 'pending' && task.status !== 'ready'
      if (
        started &&
        (task.spec !== requested.spec ||
          task.deps !== desiredDeps ||
          task.auto_options !== nextOptions ||
          Boolean(task.needs_coordinator_review) !== requested.review)
      ) {
        throw new OrchestrationError(
          'workflow_task_started',
          `Task ${task.source_key} is ${task.status}; only not-yet-started Tasks can change.`
        )
      }
      if (!started) {
        const display = buildOrchestrationTaskDisplayMetadata({
          spec: requested.spec,
          taskTitle: requested.title,
          displayName: requested.displayName
        })
        this.db
          .prepare(
            `UPDATE tasks SET spec = ?, task_title = ?, display_name = ?, deps = ?,
               auto_options = ?, review_role = ?, review_of_task_id = ?,
               needs_coordinator_review = ?
             WHERE id = ?`
          )
          .run(
            requested.spec,
            display.taskTitle || null,
            display.displayName || null,
            desiredDeps,
            nextOptions,
            requested.reviewRole,
            requested.reviewOf ? (idByKey.get(requested.reviewOf) ?? null) : null,
            requested.review ? 1 : 0,
            task.id
          )
        updated++
      }
    }
    for (const removedId of removedIds) {
      const referenced = this.db
        .prepare(
          `SELECT 1 FROM tasks
           WHERE run_id = ? AND id NOT IN (${[...removedIds].map(() => '?').join(',')})
             AND EXISTS (SELECT 1 FROM json_each(tasks.deps) WHERE value = ?) LIMIT 1`
        )
        .get(params.runId, ...removedIds, removedId)
      if (referenced) {
        throw new OrchestrationError(
          'invalid_argument',
          'A removed Task is still a dependency; remove its dependents in the same workflow update.'
        )
      }
    }
    for (const removedId of removedIds) {
      this.db.prepare('DELETE FROM tasks WHERE id = ?').run(removedId)
    }
    for (const requested of params.workflow.tasks) {
      const taskId = idByKey.get(requested.key) as string
      if (existingByKey.has(requested.key)) {
        continue
      }
      const deps = requested.dependsOn.map((key) => idByKey.get(key) as string)
      const display = buildOrchestrationTaskDisplayMetadata({
        spec: requested.spec,
        taskTitle: requested.title,
        displayName: requested.displayName
      })
      const ready = deps.every((depId) => this.getTask(depId)?.status === 'completed')
      this.db
        .prepare(
          `INSERT INTO tasks (
             id, run_id, task_title, display_name, spec, status, deps, source_key,
             auto_options, review_role, review_of_task_id, needs_coordinator_review
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
        )
        .run(
          taskId,
          params.runId,
          display.taskTitle || null,
          display.displayName || null,
          requested.spec,
          ready ? 'ready' : 'pending',
          JSON.stringify(deps),
          requested.key,
          JSON.stringify(executionOptionsFor(requested)),
          requested.reviewRole,
          requested.reviewOf ? (idByKey.get(requested.reviewOf) ?? null) : null,
          requested.review ? 1 : 0
        )
    }
    refreshAutomaticTaskReadiness.call(this, params.runId)
    const workflowVersion = run.workflow_version + 1
    this.db
      .prepare(
        `UPDATE runs SET workflow_version = ?, max_parallel = ?, updated_at = datetime('now')
         WHERE id = ?`
      )
      .run(workflowVersion, params.workflow.maxParallel ?? run.max_parallel, params.runId)
    recordAutomaticRunEvent.call(this, {
      runId: params.runId,
      kind: 'workflow_applied',
      eventKey: `workflow:${params.runId}:${workflowVersion}`,
      payload: { created, updated, removed }
    })
    this.db.exec('COMMIT')
    return {
      run: this.getRun(params.runId) as RunRow,
      workflowVersion,
      created,
      updated,
      removed
    }
  } catch (error) {
    this.db.exec('ROLLBACK')
    throw error
  }
}

function executionOptionsFor(task: {
  agent?: string
  model?: string
  effort?: string
  repo?: string
  worktree?: string
  workspaceFrom?: string
  workspaceUsage: 'read' | 'write'
  timeoutMs?: number
}): OrchestrationTaskExecutionOptions {
  return {
    workspaceUsage: task.workspaceUsage,
    ...(task.agent ? { agent: task.agent } : {}),
    ...(task.model ? { model: task.model } : {}),
    ...(task.effort ? { effort: task.effort } : {}),
    ...(task.repo ? { repo: task.repo } : {}),
    ...(task.worktree ? { worktree: task.worktree } : {}),
    ...(task.workspaceFrom ? { workspaceFrom: task.workspaceFrom } : {}),
    ...(task.timeoutMs ? { timeoutMs: task.timeoutMs } : {})
  }
}

/** Promotion is by dependency completion; a workflow apply runs it for rows it did not touch. */
export function refreshAutomaticTaskReadiness(this: OrchestrationDb, runId: string): void {
  const tasks = this.db
    .prepare(
      "SELECT id, status, deps FROM tasks WHERE run_id = ? AND status IN ('pending', 'ready')"
    )
    .all(runId) as Pick<TaskRow, 'id' | 'status' | 'deps'>[]
  const statusById = new Map(
    (
      this.db.prepare('SELECT id, status FROM tasks WHERE run_id = ?').all(runId) as Pick<
        TaskRow,
        'id' | 'status'
      >[]
    ).map((task) => [task.id, task.status])
  )
  for (const task of tasks) {
    const deps: string[] = JSON.parse(task.deps)
    const ready = deps.every((depId) => statusById.get(depId) === 'completed')
    const next = ready ? 'ready' : 'pending'
    if (next !== task.status) {
      this.db.prepare('UPDATE tasks SET status = ? WHERE id = ?').run(next, task.id)
      statusById.set(task.id, next)
    }
  }
}

export type WorkflowApplyMethods = {
  applyOrchestrationWorkflow: typeof applyOrchestrationWorkflow
  refreshAutomaticTaskReadiness: typeof refreshAutomaticTaskReadiness
}

export function attachWorkflowApply(ctor: { prototype: object }): void {
  Object.assign(ctor.prototype, {
    applyOrchestrationWorkflow,
    refreshAutomaticTaskReadiness
  })
}
