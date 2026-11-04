// @vitest-environment happy-dom

import '@testing-library/jest-dom/vitest'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { DashboardSnapshot, DashboardWorkspace } from '../../../../shared/dashboard-snapshot'
import {
  createWorkspaceTodo,
  insertWorkspaceTodo,
  removeWorkspaceTodo,
  setWorkspaceTodoCompleted,
  updateWorkspaceTodoText,
  type WorkspaceTodo,
  type WorkspaceTodoAction,
  type WorkspaceTodoActionResult
} from '../../../../shared/workspace-todo'
import { i18n } from '@/i18n/i18n'
import { AgentKanbanBoard } from './AgentKanbanBoard'

vi.mock('./AgentKanbanCard', () => ({
  AgentKanbanCard: () => <div data-testid="agent-card" />
}))
vi.mock('./AgentTerminalDialog', () => ({
  AgentTerminalDialog: () => <div data-testid="terminal-dialog" />
}))

const WORKSPACE_ID = 'repo::/work/app'

function workspace(overrides: Partial<DashboardWorkspace> = {}): DashboardWorkspace {
  return {
    repoId: 'repo',
    worktreeId: WORKSPACE_ID,
    repoName: 'Repo',
    worktreeName: 'app',
    hostKind: 'local',
    executionHostId: 'local',
    workspaceKind: 'worktree',
    workspaceStatusId: 'active',
    workspaceStatusLabel: 'Active',
    todoSupport: 'supported',
    ...overrides
  }
}

function todo(text: string, overrides: Partial<WorkspaceTodo> = {}): WorkspaceTodo {
  return createWorkspaceTodo({ workspaceId: WORKSPACE_ID, text, now: 1_000, ...overrides })
}

function snapshot(
  todos: WorkspaceTodo[],
  workspaces: DashboardWorkspace[] = [workspace({ todos })]
): DashboardSnapshot {
  return {
    generatedAt: 1,
    cards: [],
    workspaces,
    activeWorkspaceId: WORKSPACE_ID,
    activeWorkspaceExecutionHostId: 'local'
  }
}

function applyAction(snapshot: DashboardSnapshot, action: WorkspaceTodoAction): DashboardSnapshot {
  return {
    ...snapshot,
    workspaces: (snapshot.workspaces ?? []).map((entry) => {
      if (entry.worktreeId !== action.workspaceId) {
        return entry
      }
      const todos = entry.todos ?? []
      switch (action.kind) {
        case 'create':
          return {
            ...entry,
            todos: insertWorkspaceTodo(
              todos,
              createWorkspaceTodo({
                workspaceId: action.workspaceId,
                text: action.text,
                id: action.todoId,
                now: action.now ?? 2_000
              })
            )
          }
        case 'restore':
          return { ...entry, todos: insertWorkspaceTodo(todos, action.todo) }
        case 'updateText':
          return {
            ...entry,
            todos: updateWorkspaceTodoText(todos, action.todoId, action.text, action.now ?? 2_000)
          }
        case 'setCompleted':
          return {
            ...entry,
            todos: setWorkspaceTodoCompleted(
              todos,
              action.todoId,
              action.completed,
              action.now ?? 2_000
            )
          }
        case 'delete':
          return { ...entry, todos: removeWorkspaceTodo(todos, action.todoId) }
      }
    })
  }
}

function renderBoard(
  initial: DashboardSnapshot,
  actionImpl?: (action: WorkspaceTodoAction) => Promise<WorkspaceTodoActionResult>
): { onAction: ReturnType<typeof vi.fn> } {
  const onAction = vi.fn(
    actionImpl ??
      (async () => {
        return { ok: true } as const
      })
  )
  function Harness(): React.JSX.Element {
    const [current, setCurrent] = useState(initial)
    return (
      <AgentKanbanBoard
        snapshot={current}
        onTodoAction={async (action) => {
          const result = await onAction(action)
          if (result.ok) {
            setCurrent((previous) => applyAction(previous, action))
          }
          return result
        }}
      />
    )
  }
  render(<Harness />)
  return { onAction }
}

describe('AgentKanbanBoard Todo column', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
    localStorage.clear()
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
    )
    ;(window as unknown as { api: unknown }).api = {
      dashboard: { ackAgent: vi.fn(async () => {}) }
    }
  })
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('renders the Todo column first even when no agents exist and shows the open count', () => {
    renderBoard(snapshot([todo('one'), todo('two', { id: 'two' })]))

    const regions = screen.getAllByRole('region')
    expect(regions[0]?.getAttribute('aria-label')).toBe('Todo')
    expect(within(regions[0]!).getByText('2')).toBeInTheDocument()
    expect(within(regions[0]!).getByRole('button', { name: 'Add todo' })).toBeInTheDocument()
    expect(screen.getByText('one')).toBeInTheDocument()
  })

  it('adds a todo to the active workspace from the keyboard and puts it on top', async () => {
    const { onAction } = renderBoard(snapshot([]))

    fireEvent.click(screen.getByRole('button', { name: 'Add todo' }))
    const input = screen.getByLabelText('New todo')
    expect(input).toHaveFocus()
    expect(screen.getByRole('combobox', { name: 'Todo workspace' })).toHaveTextContent('app')
    fireEvent.change(input, { target: { value: 'Ship the todo column' } })
    fireEvent.submit(input.closest('form')!)

    expect(await screen.findByText('Ship the todo column')).toBeInTheDocument()
    const card = screen.getByTestId('todo-card')
    expect(card.textContent).toContain('app')
    expect(onAction).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'create',
        workspaceId: WORKSPACE_ID,
        text: 'Ship the todo column'
      })
    )
    expect(screen.queryByLabelText('New todo')).not.toBeInTheDocument()
  })

  it('reuses the client todo id when a failed create is retried', async () => {
    const ids: string[] = []
    renderBoard(snapshot([]), async (action) => {
      if (action.kind !== 'create') {
        return { ok: true }
      }
      ids.push(action.todoId ?? '')
      return ids.length === 1
        ? { ok: false, code: 'save-failed', error: 'Timed out' }
        : { ok: true }
    })

    fireEvent.click(screen.getByRole('button', { name: 'Add todo' }))
    const input = screen.getByLabelText('New todo')
    fireEvent.change(input, { target: { value: 'Retry me' } })
    fireEvent.submit(input.closest('form')!)
    expect(await screen.findByText('Timed out')).toBeInTheDocument()

    fireEvent.submit(input.closest('form')!)
    expect(await screen.findByText('Retry me')).toBeInTheDocument()
    expect(ids).toHaveLength(2)
    expect(ids[0]).not.toBe('')
    expect(ids[1]).toBe(ids[0])
  })

  it('rejects blank text and keeps the form open', () => {
    const { onAction } = renderBoard(snapshot([]))

    fireEvent.click(screen.getByRole('button', { name: 'Add todo' }))
    fireEvent.submit(screen.getByLabelText('New todo').closest('form')!)

    expect(onAction).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a todo before saving.')
    expect(screen.getByLabelText('New todo')).toBeInTheDocument()
  })

  it('cancels the add form with Escape without saving', () => {
    const { onAction } = renderBoard(snapshot([]))

    fireEvent.click(screen.getByRole('button', { name: 'Add todo' }))
    const input = screen.getByLabelText('New todo')
    fireEvent.change(input, { target: { value: 'Discard me' } })
    fireEvent.keyDown(input, { key: 'Escape' })

    expect(screen.queryByLabelText('New todo')).not.toBeInTheDocument()
    expect(onAction).not.toHaveBeenCalled()
  })

  it('edits the text in place and cancels with Escape', async () => {
    const existing = todo('Before')
    renderBoard(snapshot([existing]))

    fireEvent.click(screen.getByText('Before'))
    const input = screen.getByLabelText('Edit todo')
    fireEvent.change(input, { target: { value: 'After' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(await screen.findByText('After')).toBeInTheDocument()
    expect(screen.queryByText('Before')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('After'))
    const cancel = screen.getByLabelText('Edit todo')
    fireEvent.change(cancel, { target: { value: 'Discarded' } })
    fireEvent.keyDown(cancel, { key: 'Escape' })
    expect(screen.getByText('After')).toBeInTheDocument()
  })

  it('completes into the collapsed Completed section and reopens', async () => {
    const { onAction } = renderBoard(snapshot([todo('Finish me')]))

    fireEvent.click(screen.getByRole('checkbox', { name: 'Mark todo done' }))
    expect(await screen.findByText('Completed')).toBeInTheDocument()
    expect(screen.getByText('(1)')).toBeInTheDocument()
    expect(screen.queryByText('Finish me')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('Completed'))
    const completedCard = await screen.findByTestId('todo-card')
    expect(completedCard.dataset.completed).toBe('true')
    fireEvent.click(within(completedCard).getByRole('checkbox', { name: 'Reopen todo' }))
    expect(onAction).toHaveBeenLastCalledWith(
      expect.objectContaining({ kind: 'setCompleted', completed: false })
    )

    await waitFor(() => {
      expect(screen.queryByText('Completed')).not.toBeInTheDocument()
    })
    expect(screen.getByTestId('todo-card').dataset.completed).toBe('false')
    expect(screen.getByText('Finish me')).toBeInTheDocument()
    expect(screen.queryByText('Completed')).not.toBeInTheDocument()
  })

  it('deletes from the card menu and restores through Undo', async () => {
    renderBoard(snapshot([todo('Delete me')]))

    fireEvent.pointerDown(screen.getByRole('button', { name: 'Todo actions' }))
    fireEvent.click(await screen.findByText('Delete todo'))

    expect(await screen.findByText('Todo deleted.')).toBeInTheDocument()
    expect(screen.queryByText('Delete me')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(await screen.findByText('Delete me')).toBeInTheDocument()
    expect(screen.queryByText('Todo deleted.')).not.toBeInTheDocument()
  })

  it('keeps one Undo entry per deletion instead of overwriting the previous', async () => {
    renderBoard(snapshot([todo('first'), todo('second', { id: 'second' })]))

    const deleteTodo = async (text: string): Promise<void> => {
      const card = screen.getByText(text).closest('[data-testid="todo-card"]')
      if (!(card instanceof HTMLElement)) {
        throw new Error(`Todo card not found for ${text}`)
      }
      fireEvent.pointerDown(within(card).getByRole('button', { name: 'Todo actions' }))
      fireEvent.click(await screen.findByText('Delete todo'))
    }

    await deleteTodo('first')
    expect(await screen.findByText('Todo deleted.')).toBeInTheDocument()
    await deleteTodo('second')
    expect(await screen.findByText('2 todos deleted.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(await screen.findByText('second')).toBeInTheDocument()
    expect(screen.getByText('Todo deleted.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(await screen.findByText('first')).toBeInTheDocument()
    expect(screen.queryByText(/todos? deleted/)).not.toBeInTheDocument()
  })

  it('filters todo text through board search', () => {
    renderBoard(snapshot([todo('repair relay'), todo('dashboard polish', { id: 'two' })]))

    fireEvent.change(screen.getByLabelText('Search agents'), { target: { value: 'relay' } })

    expect(screen.getByText('repair relay')).toBeInTheDocument()
    expect(screen.queryByText('dashboard polish')).not.toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('keeps the draft visible and does not complete after a save failure', async () => {
    const existing = todo('Cannot save')
    renderBoard(snapshot([existing]), async (action) =>
      action.kind === 'create'
        ? { ok: false, code: 'save-failed', error: 'Save failed' }
        : { ok: true }
    )

    fireEvent.click(screen.getByRole('button', { name: 'Add todo' }))
    const input = screen.getByLabelText('New todo')
    fireEvent.change(input, { target: { value: 'Keep this draft' } })
    fireEvent.submit(input.closest('form')!)

    expect(await screen.findByText('Save failed')).toBeInTheDocument()
    expect(input).toHaveValue('Keep this draft')
    expect(screen.getByLabelText('New todo')).toBeInTheDocument()
  })

  it('does not check completion before the host confirms it', async () => {
    let resolve: ((result: WorkspaceTodoActionResult) => void) | undefined
    const pending = new Promise<WorkspaceTodoActionResult>((settle) => {
      resolve = settle
    })
    renderBoard(snapshot([todo('Wait for save')]), async (action) =>
      action.kind === 'setCompleted' ? pending : { ok: true }
    )

    const checkbox = screen.getByRole('checkbox', { name: 'Mark todo done' })
    fireEvent.click(checkbox)
    expect(checkbox).toHaveAttribute('data-state', 'unchecked')

    await act(async () => {
      resolve?.({ ok: false, code: 'save-failed', error: 'Could not save' })
      await pending
    })
    expect(await screen.findByText('Could not save')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Mark todo done' })).toHaveAttribute(
      'data-state',
      'unchecked'
    )
  })

  it('shows an unsupported-host message and hides the add form', () => {
    renderBoard(snapshot([], [workspace({ todoSupport: 'unsupported' })]))

    expect(screen.getByText('This host does not support workspace todos.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add todo' })).not.toBeInTheDocument()
  })
})
