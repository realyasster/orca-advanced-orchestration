import type { WorktreeSlice } from '../../worktree-helpers'
import type { WorktreeSliceGet } from '../listing/worktree-slice-types'
import { parseExecutionHostId, type ExecutionHostId } from '../../../../../../shared/execution-host'
import {
  peekRuntimeEnvironmentCapability,
  runtimeEnvironmentSupportsCapability
} from '@/runtime/runtime-rpc-client'
import { WORKSPACE_TODO_RUNTIME_CAPABILITY } from '../../../../../../shared/worktree-runtime-capabilities'
import { translate } from '@/i18n/i18n'
import {
  createWorkspaceTodo,
  insertWorkspaceTodo,
  isValidWorkspaceTodoText,
  normalizeWorkspaceTodos,
  removeWorkspaceTodo,
  setWorkspaceTodoCompleted,
  updateWorkspaceTodoText,
  WorkspaceTodoLimitError,
  type WorkspaceTodo,
  type WorkspaceTodoAction,
  type WorkspaceTodoActionResult
} from '../../../../../../shared/workspace-todo'

function failure(
  code: Extract<WorkspaceTodoActionResult, { ok: false }>['code'],
  error: string
): WorkspaceTodoActionResult {
  return { ok: false, code, error }
}

function invalidText(): WorkspaceTodoActionResult {
  return failure(
    'invalid',
    translate('dashboardPopout.todo.error.invalid', 'Enter a todo before saving.')
  )
}

function unsupportedHost(): WorkspaceTodoActionResult {
  return failure(
    'unsupported',
    translate(
      'dashboardPopout.todo.error.unsupported',
      'This host does not support workspace todos.'
    )
  )
}

function limitReached(): WorkspaceTodoActionResult {
  return failure(
    'limit',
    translate('dashboardPopout.todo.error.limit', 'This workspace has reached its todo limit.')
  )
}

function missingTodo(): WorkspaceTodoActionResult {
  return failure(
    'not-found',
    translate('dashboardPopout.todo.error.missingTodo', 'This todo no longer exists.')
  )
}

/** Probe unknown remote hosts once; a negative or unreachable verdict must block the write. */
async function unsupportedHostResult(
  executionHostId: ExecutionHostId | undefined
): Promise<WorkspaceTodoActionResult | null> {
  const parsed = executionHostId ? parseExecutionHostId(executionHostId) : null
  if (parsed?.kind !== 'runtime') {
    return null
  }
  const environmentId = parsed.environmentId
  const cached = peekRuntimeEnvironmentCapability(environmentId, WORKSPACE_TODO_RUNTIME_CAPABILITY)
  if (cached === true) {
    return null
  }
  if (cached === false) {
    return unsupportedHost()
  }
  try {
    return (await runtimeEnvironmentSupportsCapability(
      environmentId,
      WORKSPACE_TODO_RUNTIME_CAPABILITY
    ))
      ? null
      : unsupportedHost()
  } catch (err) {
    return failure('save-failed', err instanceof Error ? err.message : String(err))
  }
}

function insertOrLimit(
  todos: readonly WorkspaceTodo[],
  todo: WorkspaceTodo
): WorkspaceTodo[] | WorkspaceTodoActionResult {
  try {
    return insertWorkspaceTodo(todos, todo)
  } catch (err) {
    if (err instanceof WorkspaceTodoLimitError) {
      return limitReached()
    }
    throw err
  }
}

export function createApplyWorkspaceTodoAction(
  get: WorktreeSliceGet
): WorktreeSlice['applyWorkspaceTodoAction'] {
  const queues = new Map<string, Promise<WorkspaceTodoActionResult>>()

  const run = async (action: WorkspaceTodoAction): Promise<WorkspaceTodoActionResult> => {
    const workspace = get().getKnownWorktreeById(action.workspaceId, action.executionHostId)
    if (!workspace) {
      return failure(
        'not-found',
        translate(
          'dashboardPopout.todo.error.missingWorkspace',
          'This workspace is no longer available.'
        )
      )
    }
    const executionHostId = action.executionHostId ?? workspace.hostId
    const todos = normalizeWorkspaceTodos(workspace.todos)
    const now = 'now' in action && action.now !== undefined ? action.now : Date.now()
    let nextTodos: WorkspaceTodo[]
    let changed = true

    switch (action.kind) {
      case 'create': {
        if (!isValidWorkspaceTodoText(action.text)) {
          return invalidText()
        }
        // Retries after an IPC timeout reuse the client id; only insert it once.
        if (action.todoId && todos.some((entry) => entry.id === action.todoId)) {
          return { ok: true, changed: false }
        }
        const inserted = insertOrLimit(
          todos,
          createWorkspaceTodo({
            workspaceId: action.workspaceId,
            text: action.text,
            id: action.todoId,
            now
          })
        )
        if (!Array.isArray(inserted)) {
          return inserted
        }
        nextTodos = inserted
        break
      }
      case 'restore': {
        if (!isValidWorkspaceTodoText(action.todo.text)) {
          return invalidText()
        }
        if (todos.some((entry) => entry.id === action.todo.id)) {
          return { ok: true, changed: false }
        }
        const inserted = insertOrLimit(todos, {
          ...action.todo,
          workspaceId: action.workspaceId
        })
        if (!Array.isArray(inserted)) {
          return inserted
        }
        nextTodos = inserted
        break
      }
      case 'updateText': {
        if (!isValidWorkspaceTodoText(action.text)) {
          return invalidText()
        }
        const todo = todos.find((entry) => entry.id === action.todoId)
        if (!todo) {
          return missingTodo()
        }
        const text = action.text.trim()
        if (todo.text === text) {
          return { ok: true, changed: false }
        }
        nextTodos = updateWorkspaceTodoText(todos, action.todoId, text, now)
        break
      }
      case 'setCompleted': {
        const todo = todos.find((entry) => entry.id === action.todoId)
        if (!todo) {
          return missingTodo()
        }
        if ((todo.completedAt !== null) === action.completed) {
          return { ok: true, changed: false }
        }
        nextTodos = setWorkspaceTodoCompleted(todos, action.todoId, action.completed, now)
        break
      }
      case 'delete': {
        if (!todos.some((entry) => entry.id === action.todoId)) {
          return { ok: true, changed: false }
        }
        nextTodos = removeWorkspaceTodo(todos, action.todoId)
        break
      }
    }

    const unsupported = await unsupportedHostResult(executionHostId)
    if (unsupported) {
      return unsupported
    }

    const result = await get().updateWorktreeMeta(
      action.workspaceId,
      { todos: nextTodos },
      { executionHostId, deferOptimistic: true }
    )
    if (!result.ok) {
      return failure('save-failed', result.error)
    }
    return { ok: true, changed }
  }

  return (action) => {
    // serialise read-modify-write cycles per workspace so deferred saves cannot overwrite each other.
    const key = action.workspaceId
    const previous = queues.get(key) ?? Promise.resolve<WorkspaceTodoActionResult>({ ok: true })
    const next = previous
      .catch(() => undefined)
      .then(() => run(action))
      .catch((err: unknown) =>
        failure('save-failed', err instanceof Error ? err.message : String(err))
      )
    queues.set(key, next)
    const settle = (): void => {
      if (queues.get(key) === next) {
        queues.delete(key)
      }
    }
    void next.then(settle, settle)
    return next
  }
}
