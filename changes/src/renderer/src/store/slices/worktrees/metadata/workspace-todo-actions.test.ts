import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { WorktreeSliceGet } from '../listing/worktree-slice-types'
import type { WorkspaceTodo } from '../../../../../../shared/workspace-todo'

const runtimeMocks = vi.hoisted(() => ({
  peek: vi.fn(),
  supports: vi.fn()
}))

vi.mock('@/runtime/runtime-rpc-client', () => ({
  peekRuntimeEnvironmentCapability: runtimeMocks.peek,
  runtimeEnvironmentSupportsCapability: runtimeMocks.supports
}))

import { createApplyWorkspaceTodoAction } from './workspace-todo-actions'

function createHarness(initial: WorkspaceTodo[] = [], hostId = 'local') {
  const state = { todos: initial, writes: 0 }
  const get = (() => ({
    getKnownWorktreeById: () => ({ id: 'w1', hostId, todos: state.todos }),
    updateWorktreeMeta: vi.fn(async (_id: string, updates: { todos?: WorkspaceTodo[] }) => {
      await new Promise((resolve) => setTimeout(resolve, 1))
      state.writes += 1
      state.todos = updates.todos ?? state.todos
      return { ok: true as const }
    })
  })) as unknown as WorktreeSliceGet
  return { apply: createApplyWorkspaceTodoAction(get), state }
}

describe('applyWorkspaceTodoAction', () => {
  beforeEach(() => {
    runtimeMocks.peek.mockReset()
    runtimeMocks.supports.mockReset()
  })

  it('serialises read-modify-write cycles so concurrent creates both survive', async () => {
    const { apply, state } = createHarness()

    const results = await Promise.all([
      apply({ kind: 'create', workspaceId: 'w1', text: 'first', todoId: 'a' }),
      apply({ kind: 'create', workspaceId: 'w1', text: 'second', todoId: 'b' })
    ])

    expect(results).toEqual([
      { ok: true, changed: true },
      { ok: true, changed: true }
    ])
    expect(state.writes).toBe(2)
    expect(state.todos.map((todo) => todo.id).sort()).toEqual(['a', 'b'])
  })

  it('treats a retried client id as idempotent', async () => {
    const { apply, state } = createHarness()

    await expect(
      apply({ kind: 'create', workspaceId: 'w1', text: 'once', todoId: 'same' })
    ).resolves.toEqual({ ok: true, changed: true })
    await expect(
      apply({ kind: 'create', workspaceId: 'w1', text: 'once', todoId: 'same' })
    ).resolves.toEqual({ ok: true, changed: false })

    expect(state.writes).toBe(1)
    expect(state.todos).toHaveLength(1)
  })

  it('does not write or report success for a delete of a missing todo', async () => {
    const { apply, state } = createHarness()

    await expect(apply({ kind: 'delete', workspaceId: 'w1', todoId: 'missing' })).resolves.toEqual({
      ok: true,
      changed: false
    })
    expect(state.writes).toBe(0)
  })

  it('probes an unknown runtime capability and blocks the write when unsupported', async () => {
    runtimeMocks.peek.mockReturnValue(undefined)
    runtimeMocks.supports.mockResolvedValue(false)
    const { apply, state } = createHarness([], 'runtime:env-1')

    await expect(
      apply({ kind: 'create', workspaceId: 'w1', text: 'blocked', todoId: 'x' })
    ).resolves.toEqual({
      ok: false,
      code: 'unsupported',
      error: 'This host does not support workspace todos.'
    })
    expect(runtimeMocks.supports).toHaveBeenCalledWith('env-1', 'workspace.todo.v1')
    expect(state.writes).toBe(0)
  })

  it('does not write when a probed capability check fails', async () => {
    runtimeMocks.peek.mockReturnValue(undefined)
    runtimeMocks.supports.mockRejectedValue(new Error('offline'))
    const { apply, state } = createHarness([], 'runtime:env-1')

    await expect(
      apply({ kind: 'create', workspaceId: 'w1', text: 'blocked', todoId: 'x' })
    ).resolves.toEqual({ ok: false, code: 'save-failed', error: 'offline' })
    expect(state.writes).toBe(0)
  })
})
