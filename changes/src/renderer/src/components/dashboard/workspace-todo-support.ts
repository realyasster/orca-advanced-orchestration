import type { ExecutionHostId } from '../../../../shared/execution-host'
import { parseExecutionHostId } from '../../../../shared/execution-host'
import { normalizeWorkspaceTodos, type WorkspaceTodo } from '../../../../shared/workspace-todo'
import { WORKSPACE_TODO_RUNTIME_CAPABILITY } from '../../../../shared/worktree-runtime-capabilities'
import { peekRuntimeEnvironmentCapability } from '@/runtime/runtime-rpc-client'

/** A definitive negative capability verdict warns before a save; unknown hosts keep the normal form ready. */
export function resolveWorkspaceTodoSupport(
  executionHostId: ExecutionHostId
): 'supported' | 'unsupported' {
  const parsed = parseExecutionHostId(executionHostId)
  if (parsed?.kind !== 'runtime') {
    return 'supported'
  }
  return peekRuntimeEnvironmentCapability(
    parsed.environmentId,
    WORKSPACE_TODO_RUNTIME_CAPABILITY
  ) === false
    ? 'unsupported'
    : 'supported'
}

// The bridge republishes snapshots several times per second; the store only replaces this array on change.
const normalizedTodoCache = new WeakMap<readonly WorkspaceTodo[], WorkspaceTodo[]>()

export function workspaceTodosForSnapshot(
  todos: readonly WorkspaceTodo[] | undefined,
  workspaceId: string
): WorkspaceTodo[] {
  if (!todos) {
    return []
  }
  const cached = normalizedTodoCache.get(todos)
  if (cached && cached.every((todo) => todo.workspaceId === workspaceId)) {
    return cached
  }
  const normalized = normalizeWorkspaceTodos(todos).map((todo) =>
    todo.workspaceId === workspaceId ? todo : { ...todo, workspaceId }
  )
  normalizedTodoCache.set(todos, normalized)
  return normalized
}
