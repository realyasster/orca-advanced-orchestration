import type { ExecutionHostId } from './execution-host'
import { createNonSecureContextUuid } from './non-secure-context-uuid'

/** Manual workspace work items are independent from the agent lifecycle. */
export const WORKSPACE_TODO_MAX_TEXT_LENGTH = 2_000
export const WORKSPACE_TODO_MAX_ITEMS = 500

export type WorkspaceTodo = {
  /** Stable identity; survives text and completion edits. */
  id: string
  /** Orca workspace identity (worktree id or folder:<id>). */
  workspaceId: string
  text: string
  createdAt: number
  updatedAt: number
  completedAt: number | null
}

export type WorkspaceTodoAction =
  | {
      kind: 'create'
      workspaceId: string
      executionHostId?: ExecutionHostId
      text: string
      todoId?: string
      now?: number
    }
  | {
      kind: 'updateText'
      workspaceId: string
      executionHostId?: ExecutionHostId
      todoId: string
      text: string
      now?: number
    }
  | {
      kind: 'setCompleted'
      workspaceId: string
      executionHostId?: ExecutionHostId
      todoId: string
      completed: boolean
      now?: number
    }
  | {
      kind: 'delete'
      workspaceId: string
      executionHostId?: ExecutionHostId
      todoId: string
    }
  | {
      kind: 'restore'
      workspaceId: string
      executionHostId?: ExecutionHostId
      todo: WorkspaceTodo
    }

export type WorkspaceTodoActionErrorCode =
  | 'invalid'
  | 'not-found'
  | 'unsupported'
  | 'save-failed'
  | 'limit'

export const WORKSPACE_TODO_ACTION_ERROR_CODES: readonly WorkspaceTodoActionErrorCode[] = [
  'invalid',
  'not-found',
  'unsupported',
  'save-failed',
  'limit'
]

export class WorkspaceTodoLimitError extends Error {
  readonly code = 'workspace-todo-limit' as const

  constructor() {
    super(`A workspace can contain at most ${WORKSPACE_TODO_MAX_ITEMS} todos.`)
    this.name = 'WorkspaceTodoLimitError'
  }
}

export function isWorkspaceTodoActionErrorCode(
  value: unknown
): value is WorkspaceTodoActionErrorCode {
  return (
    typeof value === 'string' &&
    (WORKSPACE_TODO_ACTION_ERROR_CODES as readonly string[]).includes(value)
  )
}

export type WorkspaceTodoActionResult =
  | {
      ok: true
      /** False for an idempotent retry or a missing delete; callers must not show a success effect. */
      changed?: boolean
    }
  | { ok: false; code: WorkspaceTodoActionErrorCode; error: string }

/** Round-trip envelope used when the presentation-only pop-out asks the main window to mutate. */
export type WorkspaceTodoRelayRequest = {
  requestId: string
  action: WorkspaceTodoAction
}

export type WorkspaceTodoRelayResponse = {
  requestId: string
  result: WorkspaceTodoActionResult
}

function isFiniteTimestamp(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
}

export function normalizeWorkspaceTodoText(value: string): string {
  return value.trim()
}

export function isValidWorkspaceTodoText(value: string): boolean {
  const text = normalizeWorkspaceTodoText(value)
  return text.length > 0 && text.length <= WORKSPACE_TODO_MAX_TEXT_LENGTH
}

export function isWorkspaceTodo(value: unknown): value is WorkspaceTodo {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return false
  }
  const todo = value as Record<string, unknown>
  return (
    typeof todo.id === 'string' &&
    todo.id.length > 0 &&
    typeof todo.workspaceId === 'string' &&
    todo.workspaceId.length > 0 &&
    typeof todo.text === 'string' &&
    isValidWorkspaceTodoText(todo.text) &&
    isFiniteTimestamp(todo.createdAt) &&
    isFiniteTimestamp(todo.updatedAt) &&
    (todo.completedAt === null || isFiniteTimestamp(todo.completedAt))
  )
}

/** Drop corrupt persisted rows without discarding valid siblings; newest id wins, then cap. */
export function normalizeWorkspaceTodos(value: unknown): WorkspaceTodo[] {
  if (!Array.isArray(value)) {
    return []
  }
  const sorted = value.filter(isWorkspaceTodo).sort((a, b) => {
    return b.createdAt - a.createdAt || b.updatedAt - a.updatedAt || a.id.localeCompare(b.id)
  })
  const seen = new Set<string>()
  const unique: WorkspaceTodo[] = []
  for (const todo of sorted) {
    if (seen.has(todo.id)) {
      continue
    }
    seen.add(todo.id)
    unique.push(todo)
    if (unique.length === WORKSPACE_TODO_MAX_ITEMS) {
      break
    }
  }
  return unique
}

export function compareTodosByCreatedAtDesc(a: WorkspaceTodo, b: WorkspaceTodo): number {
  return b.createdAt - a.createdAt || a.id.localeCompare(b.id)
}

export function compareCompletedTodosDesc(a: WorkspaceTodo, b: WorkspaceTodo): number {
  return (b.completedAt ?? 0) - (a.completedAt ?? 0) || compareTodosByCreatedAtDesc(a, b)
}

export function createWorkspaceTodo(input: {
  workspaceId: string
  text: string
  id?: string
  now?: number
}): WorkspaceTodo {
  const now = input.now ?? Date.now()
  return {
    id: input.id ?? createNonSecureContextUuid(),
    workspaceId: input.workspaceId,
    text: normalizeWorkspaceTodoText(input.text),
    createdAt: now,
    updatedAt: now,
    completedAt: null
  }
}

/** Reject overflow instead of silently dropping the oldest todo on create/restore. */
export function insertWorkspaceTodo(
  todos: readonly WorkspaceTodo[],
  todo: WorkspaceTodo
): WorkspaceTodo[] {
  const next = [todo, ...todos.filter((entry) => entry.id !== todo.id)]
  if (next.length > WORKSPACE_TODO_MAX_ITEMS) {
    throw new WorkspaceTodoLimitError()
  }
  return next.sort(compareTodosByCreatedAtDesc)
}

export function updateWorkspaceTodoText(
  todos: readonly WorkspaceTodo[],
  todoId: string,
  text: string,
  now: number
): WorkspaceTodo[] {
  const normalized = normalizeWorkspaceTodoText(text)
  return todos.map((todo) =>
    todo.id === todoId ? { ...todo, text: normalized, updatedAt: now } : todo
  )
}

export function setWorkspaceTodoCompleted(
  todos: readonly WorkspaceTodo[],
  todoId: string,
  completed: boolean,
  now: number
): WorkspaceTodo[] {
  return todos.map((todo) =>
    todo.id === todoId ? { ...todo, completedAt: completed ? now : null, updatedAt: now } : todo
  )
}

export function removeWorkspaceTodo(
  todos: readonly WorkspaceTodo[],
  todoId: string
): WorkspaceTodo[] {
  return todos.filter((todo) => todo.id !== todoId)
}

/** Completed items remain in the same workspace list and can be reopened. */
export function splitWorkspaceTodos(todos: readonly WorkspaceTodo[]): {
  open: WorkspaceTodo[]
  completed: WorkspaceTodo[]
} {
  const open: WorkspaceTodo[] = []
  const completed: WorkspaceTodo[] = []
  for (const todo of todos) {
    if (todo.completedAt === null) {
      open.push(todo)
    } else {
      completed.push(todo)
    }
  }
  open.sort(compareTodosByCreatedAtDesc)
  completed.sort(compareCompletedTodosDesc)
  return { open, completed }
}

export function isWorkspaceTodoAction(value: unknown): value is WorkspaceTodoAction {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return false
  }
  const action = value as Record<string, unknown>
  if (typeof action.workspaceId !== 'string' || action.workspaceId.length === 0) {
    return false
  }
  if (action.executionHostId !== undefined && typeof action.executionHostId !== 'string') {
    return false
  }
  switch (action.kind) {
    case 'create':
      return (
        typeof action.text === 'string' &&
        (action.todoId === undefined || typeof action.todoId === 'string') &&
        (action.now === undefined || isFiniteTimestamp(action.now))
      )
    case 'updateText':
      return (
        typeof action.todoId === 'string' &&
        typeof action.text === 'string' &&
        (action.now === undefined || isFiniteTimestamp(action.now))
      )
    case 'setCompleted':
      return (
        typeof action.todoId === 'string' &&
        typeof action.completed === 'boolean' &&
        (action.now === undefined || isFiniteTimestamp(action.now))
      )
    case 'delete':
      return typeof action.todoId === 'string'
    case 'restore':
      return isWorkspaceTodo(action.todo) && action.todo.workspaceId === action.workspaceId
    default:
      return false
  }
}
