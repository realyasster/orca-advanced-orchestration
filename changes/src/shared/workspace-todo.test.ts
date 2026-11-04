import { describe, expect, it } from 'vitest'
import {
  createWorkspaceTodo,
  insertWorkspaceTodo,
  isValidWorkspaceTodoText,
  normalizeWorkspaceTodos,
  removeWorkspaceTodo,
  setWorkspaceTodoCompleted,
  splitWorkspaceTodos,
  updateWorkspaceTodoText,
  WorkspaceTodoLimitError,
  WORKSPACE_TODO_MAX_ITEMS,
  type WorkspaceTodo
} from './workspace-todo'

const workspaceId = 'repo::/work/app'

function todo(overrides: Partial<WorkspaceTodo> = {}): WorkspaceTodo {
  return {
    id: 'todo-1',
    workspaceId,
    text: 'Write release notes',
    createdAt: 1_000,
    updatedAt: 1_000,
    completedAt: null,
    ...overrides
  }
}

describe('workspace todos', () => {
  it('trims text, orders new items first, and keeps completed items in place', () => {
    const first = createWorkspaceTodo({ workspaceId, text: '  first  ', id: 'a', now: 1 })
    const second = createWorkspaceTodo({ workspaceId, text: 'second', id: 'b', now: 2 })
    const inserted = insertWorkspaceTodo([first], second)

    expect(inserted.map((entry) => entry.id)).toEqual(['b', 'a'])
    expect(inserted[1]?.text).toBe('first')

    const completed = setWorkspaceTodoCompleted(inserted, 'b', true, 3)
    const split = splitWorkspaceTodos(completed)
    expect(split.open.map((entry) => entry.id)).toEqual(['a'])
    expect(split.completed.map((entry) => entry.id)).toEqual(['b'])
    expect(split.completed[0]?.completedAt).toBe(3)
  })

  it('edits text and removes items by identity', () => {
    const updated = updateWorkspaceTodoText([todo()], 'todo-1', '  revised  ', 2_000)
    expect(updated[0]).toMatchObject({ text: 'revised', updatedAt: 2_000 })
    expect(removeWorkspaceTodo(updated, 'todo-1')).toEqual([])
  })

  it('rejects blank and overlong text', () => {
    expect(isValidWorkspaceTodoText('   ')).toBe(false)
    expect(isValidWorkspaceTodoText('x'.repeat(2_001))).toBe(false)
    expect(isValidWorkspaceTodoText('  keep  ')).toBe(true)
  })

  it('drops malformed persisted rows without losing valid siblings', () => {
    const normalized = normalizeWorkspaceTodos([
      todo({ id: 'valid' }),
      { ...todo({ id: 'blank' }), text: '   ' },
      { ...todo({ id: 'bad-time' }), createdAt: Number.NaN },
      null
    ])
    expect(normalized.map((entry) => entry.id)).toEqual(['valid'])
  })

  it('rejects an insertion that would exceed the workspace limit', () => {
    const full = Array.from({ length: WORKSPACE_TODO_MAX_ITEMS }, (_, index) =>
      todo({ id: `t-${index}`, createdAt: index })
    )

    expect(() => insertWorkspaceTodo(full, todo({ id: 'overflow' }))).toThrow(
      WorkspaceTodoLimitError
    )
    expect(full).toHaveLength(WORKSPACE_TODO_MAX_ITEMS)
    expect(full.some((entry) => entry.id === 'overflow')).toBe(false)
  })

  it('deduplicates ids after sorting and before applying the cap', () => {
    const normalized = normalizeWorkspaceTodos([
      todo({ id: 'duplicate', text: 'older', createdAt: 1 }),
      todo({ id: 'duplicate', text: 'newer', createdAt: 2 }),
      todo({ id: 'keep', createdAt: 3 })
    ])

    expect(normalized.map((entry) => entry.id)).toEqual(['keep', 'duplicate'])
    expect(normalized[1]?.text).toBe('newer')
  })

  it('keeps the same-named workspaces isolated by workspace identity', () => {
    const other = createWorkspaceTodo({
      workspaceId: 'repo::/work/other',
      text: 'other workspace',
      id: 'other',
      now: 3
    })
    expect(
      normalizeWorkspaceTodos([todo({ id: 'mine' }), other]).map((entry) => entry.workspaceId)
    ).toEqual(['repo::/work/app', 'repo::/work/other'])
  })
})
