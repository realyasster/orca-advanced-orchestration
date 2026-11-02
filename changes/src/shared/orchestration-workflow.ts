import { z } from 'zod'

export const ORCHESTRATION_WORKFLOW_VERSION = 1
export const ORCHESTRATION_WORKFLOW_MAX_PARALLEL_DEFAULT = 2
export const ORCHESTRATION_WORKFLOW_MAX_CORRECTION_ROUNDS = 2

const workflowKey = z
  .string()
  .min(1)
  .max(128)
  .regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/, 'Task keys allow letters, digits, _ . : and -')

export const OrchestrationWorkflowTask = z.object({
  key: workflowKey,
  spec: z.string().min(1),
  title: z.string().min(1).max(200).optional(),
  displayName: z.string().min(1).max(200).optional(),
  dependsOn: z.array(workflowKey).max(64).default([]),
  agent: z.string().min(1).max(64).optional(),
  model: z.string().min(1).max(200).optional(),
  effort: z.string().min(1).max(200).optional(),
  repo: z.string().min(1).max(512).optional(),
  worktree: z.string().min(1).max(512).optional(),
  /** Reuse the workspace another workflow Task resolved after launch. */
  workspaceFrom: workflowKey.optional(),
  /** Write tasks get isolated capacity; read tasks are verification work. */
  workspaceUsage: z.enum(['read', 'write']).default('write'),
  /** Ask the coordinator to review this Task's completion before unlocking dependents. */
  review: z.boolean().default(false),
  /** An explicit review Task reports approved/changes_requested instead of plain success. */
  reviewRole: z.enum(['normal', 'review', 'correction']).default('normal'),
  reviewOf: workflowKey.optional(),
  timeoutMs: z.number().int().min(1).max(1_800_000).optional()
})

export const OrchestrationWorkflow = z.object({
  version: z.literal(ORCHESTRATION_WORKFLOW_VERSION).default(ORCHESTRATION_WORKFLOW_VERSION),
  /** Omitted keeps the Run's max_parallel chosen at run-create. */
  maxParallel: z.number().int().min(1).max(8).optional(),
  tasks: z.array(OrchestrationWorkflowTask).min(1).max(256)
})

export type OrchestrationWorkflowTaskInput = z.infer<typeof OrchestrationWorkflowTask>
export type OrchestrationWorkflowInput = z.infer<typeof OrchestrationWorkflow>

export type OrchestrationWorkflowProblem = {
  code:
    | 'duplicate_task_key'
    | 'unknown_dependency'
    | 'cycle'
    | 'unknown_workspace_source'
    | 'invalid_review_reference'
  message: string
}

/** Validate the graph before any row is written: unique keys, existing references, and no cycles. */
export function validateOrchestrationWorkflow(
  workflow: OrchestrationWorkflowInput
): OrchestrationWorkflowProblem[] {
  const problems: OrchestrationWorkflowProblem[] = []
  const keys = new Set<string>()
  for (const task of workflow.tasks) {
    if (keys.has(task.key)) {
      problems.push({
        code: 'duplicate_task_key',
        message: `Task key ${task.key} is declared more than once.`
      })
    }
    keys.add(task.key)
  }
  for (const task of workflow.tasks) {
    for (const dependency of task.dependsOn) {
      if (!keys.has(dependency)) {
        problems.push({
          code: 'unknown_dependency',
          message: `Task ${task.key} depends on unknown Task ${dependency}.`
        })
      }
      if (dependency === task.key) {
        problems.push({
          code: 'cycle',
          message: `Task ${task.key} cannot depend on itself.`
        })
      }
    }
    if (task.workspaceFrom && !keys.has(task.workspaceFrom)) {
      problems.push({
        code: 'unknown_workspace_source',
        message: `Task ${task.key} reuses the workspace of unknown Task ${task.workspaceFrom}.`
      })
    }
    if (task.workspaceFrom && task.worktree) {
      problems.push({
        code: 'unknown_workspace_source',
        message: `Task ${task.key} cannot set both worktree and workspaceFrom.`
      })
    }
    if (task.reviewOf && !keys.has(task.reviewOf)) {
      problems.push({
        code: 'invalid_review_reference',
        message: `Task ${task.key} reviews unknown Task ${task.reviewOf}.`
      })
    }
  }
  if (problems.length === 0) {
    const dependents = new Map<string, string[]>()
    const inDegree = new Map<string, number>()
    for (const task of workflow.tasks) {
      inDegree.set(task.key, task.dependsOn.length)
      for (const dependency of task.dependsOn) {
        const list = dependents.get(dependency) ?? []
        list.push(task.key)
        dependents.set(dependency, list)
      }
    }
    const queue = [...inDegree.entries()].filter(([, degree]) => degree === 0).map(([key]) => key)
    let visited = 0
    while (queue.length > 0) {
      const key = queue.shift() as string
      visited++
      for (const dependent of dependents.get(key) ?? []) {
        const degree = (inDegree.get(dependent) ?? 0) - 1
        inDegree.set(dependent, degree)
        if (degree === 0) {
          queue.push(dependent)
        }
      }
    }
    if (visited !== workflow.tasks.length) {
      problems.push({ code: 'cycle', message: 'The workflow Task graph contains a cycle.' })
    }
  }
  return problems
}

/** JSON stored on tasks: scheduling inputs only, so the executor never re-reads the submitted file. */
export type OrchestrationTaskExecutionOptions = {
  agent?: string
  model?: string
  effort?: string
  repo?: string
  worktree?: string
  workspaceFrom?: string
  workspaceUsage: 'read' | 'write'
  timeoutMs?: number
}

export function executionOptionsOfTask(task: {
  auto_options: string
}): OrchestrationTaskExecutionOptions {
  try {
    const parsed: unknown = JSON.parse(task.auto_options)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { workspaceUsage: 'write' }
    }
    const record = parsed as Record<string, unknown>
    const usage = record.workspaceUsage === 'read' ? 'read' : 'write'
    return {
      workspaceUsage: usage,
      ...(typeof record.agent === 'string' ? { agent: record.agent } : {}),
      ...(typeof record.model === 'string' ? { model: record.model } : {}),
      ...(typeof record.effort === 'string' ? { effort: record.effort } : {}),
      ...(typeof record.repo === 'string' ? { repo: record.repo } : {}),
      ...(typeof record.worktree === 'string' ? { worktree: record.worktree } : {}),
      ...(typeof record.workspaceFrom === 'string' ? { workspaceFrom: record.workspaceFrom } : {}),
      ...(typeof record.timeoutMs === 'number' ? { timeoutMs: record.timeoutMs } : {})
    }
  } catch {
    return { workspaceUsage: 'write' }
  }
}

export type OrchestrationTaskDelivery = {
  outcome: 'succeeded' | 'failed'
  summary: string
  evidence: string[]
  handoff?: string
  reviewVerdict?: 'approved' | 'changes_requested'
  dispatchId?: string
  codeVersion?: string
  completedAt: string
}

export function deliveryOfTask(task: {
  delivery: string | null
}): OrchestrationTaskDelivery | null {
  if (!task.delivery) {
    return null
  }
  try {
    const parsed: unknown = JSON.parse(task.delivery)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return null
    }
    const record = parsed as Record<string, unknown>
    if (record.outcome !== 'succeeded' && record.outcome !== 'failed') {
      return null
    }
    return {
      outcome: record.outcome,
      summary: typeof record.summary === 'string' ? record.summary : '',
      evidence: Array.isArray(record.evidence)
        ? record.evidence.filter((item): item is string => typeof item === 'string')
        : [],
      ...(typeof record.handoff === 'string' ? { handoff: record.handoff } : {}),
      ...(record.reviewVerdict === 'approved' || record.reviewVerdict === 'changes_requested'
        ? { reviewVerdict: record.reviewVerdict }
        : {}),
      ...(typeof record.dispatchId === 'string' ? { dispatchId: record.dispatchId } : {}),
      ...(typeof record.codeVersion === 'string' ? { codeVersion: record.codeVersion } : {}),
      completedAt: typeof record.completedAt === 'string' ? record.completedAt : ''
    }
  } catch {
    return null
  }
}
