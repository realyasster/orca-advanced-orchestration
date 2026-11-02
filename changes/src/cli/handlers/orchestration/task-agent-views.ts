import type { OrchestrationAgentView } from './agent-view'

export type TaskListResult = {
  tasks: {
    id: string
    spec: string
    task_title?: string | null
    display_name?: string | null
    status: string
    assignee_handle?: string | null
    dispatch_id?: string | null
    spec_truncated?: boolean
    deps?: string
    parent_id?: string | null
    result?: string | null
    review_role?: string
    correction_round?: number
    needs_coordinator_review?: number
    worktree_id?: string | null
    wait_reason?: string
    delivery_summary?: string | null
    delivery_evidence?: string[] | null
    review_verdict?: string | null
    created_at?: string
    completed_at?: string | null
  }[]
  count: number
  runId?: string
  legacyReadOnly?: boolean
}

// The task row echoes the caller's spec back; the id and status are what it acts on.
export const TASK_RECEIPT_VIEW: OrchestrationAgentView<
  { task: { id: string; status: string } },
  { taskId: string; status: string }
> = {
  fields: (value) => ({ taskId: value.task.id, status: value.task.status })
}

export const TASK_LIST_VIEW: OrchestrationAgentView<TaskListResult, Record<string, unknown>> = {
  // Specs and results are free text that grows with the Run; --full keeps them.
  fields: (r) => ({
    tasks: r.tasks.map((task) => ({
      id: task.id,
      status: task.status,
      title: task.display_name ?? task.task_title ?? task.spec.slice(0, 60),
      deps: task.deps && task.deps !== '[]' ? task.deps : undefined,
      parentId: task.parent_id ?? undefined,
      dispatchId: task.dispatch_id ?? undefined,
      assignee: task.assignee_handle ?? undefined,
      waitReason: task.wait_reason,
      worktreeId: task.worktree_id ?? undefined,
      reviewRole: task.review_role === 'normal' ? undefined : task.review_role,
      correctionRound: task.correction_round ? task.correction_round : undefined,
      reviewVerdict: task.review_verdict ?? undefined,
      deliverySummary: task.delivery_summary ?? undefined,
      evidence: task.delivery_evidence?.length ? task.delivery_evidence : undefined,
      createdAt: task.created_at,
      completedAt: task.completed_at ?? undefined
    })),
    runId: r.runId,
    legacyReadOnly: r.legacyReadOnly || undefined
  })
}
