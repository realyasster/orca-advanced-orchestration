import { describe, expect, it } from 'vitest'
import type { DashboardWorkspace } from '../../../../shared/dashboard-snapshot'
import { createWorkspaceTodo } from '../../../../shared/workspace-todo'
import { EMPTY_DASHBOARD_FILTERS } from './agent-board-filtering'
import { filterDashboardTodos } from './workspace-todo-filtering'

function workspace(overrides: Partial<DashboardWorkspace>): DashboardWorkspace {
  return {
    repoId: 'repo-a',
    worktreeId: 'repo-a::/work/app',
    repoName: 'Repo A',
    worktreeName: 'app',
    hostKind: 'local',
    executionHostId: 'local',
    workspaceKind: 'worktree',
    ...overrides
  }
}

function todosFor(id: string, text: string) {
  return [createWorkspaceTodo({ workspaceId: id, text, now: 1 })]
}

describe('filterDashboardTodos', () => {
  const first = workspace({
    todos: todosFor('repo-a::/work/app', 'repair relay')
  })
  const second = workspace({
    repoId: 'repo-b',
    worktreeId: 'repo-b::/work/app',
    repoName: 'Repo B',
    worktreeName: 'app',
    workspaceStatusId: 'planned',
    todos: todosFor('repo-b::/work/app', 'dashboard polish')
  })

  it('searches todo text and workspace labels', () => {
    expect(filterDashboardTodos([first, second], 'relay', EMPTY_DASHBOARD_FILTERS)).toHaveLength(1)
    expect(filterDashboardTodos([first, second], 'repo b', EMPTY_DASHBOARD_FILTERS)).toHaveLength(1)
  })

  it('applies project and workspace-status filters to the todo workspace', () => {
    expect(
      filterDashboardTodos([first, second], '', {
        ...EMPTY_DASHBOARD_FILTERS,
        projects: ['repo-b']
      }).map((entry) => entry.todo.text)
    ).toEqual(['dashboard polish'])
    expect(
      filterDashboardTodos([first, second], '', {
        ...EMPTY_DASHBOARD_FILTERS,
        workspaceStatuses: ['planned']
      }).map((entry) => entry.todo.text)
    ).toEqual(['dashboard polish'])
  })

  it('does not let agent-only review filters hide todos', () => {
    expect(
      filterDashboardTodos([first, second], '', {
        ...EMPTY_DASHBOARD_FILTERS,
        reviewStates: ['open']
      })
    ).toHaveLength(2)
  })

  it('keeps same-named workspaces isolated by their ids', () => {
    const items = filterDashboardTodos([first, second], '', EMPTY_DASHBOARD_FILTERS)
    expect(items.map((entry) => entry.workspace.worktreeId)).toEqual([
      'repo-a::/work/app',
      'repo-b::/work/app'
    ])
    expect(items.map((entry) => entry.todo.workspaceId)).toEqual([
      'repo-a::/work/app',
      'repo-b::/work/app'
    ])
  })
})
