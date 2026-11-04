import type { DashboardFilters } from './agent-board-filtering'
import type { DashboardWorkspace } from '../../../../shared/dashboard-snapshot'
import type { WorkspaceTodo } from '../../../../shared/workspace-todo'
import { workspaceTodosForSnapshot } from '../dashboard/workspace-todo-support'

export type DashboardTodoItem = {
  workspace: DashboardWorkspace
  todo: WorkspaceTodo
}

/** Agent-only filters (review state) intentionally leave manual todos untouched. */
export function filterDashboardTodos(
  workspaces: readonly DashboardWorkspace[],
  query: string,
  filters: DashboardFilters
): DashboardTodoItem[] {
  const normalizedQuery = query.trim().toLowerCase()
  const items: DashboardTodoItem[] = []
  for (const workspace of workspaces) {
    if (filters.projects.length > 0 && !filters.projects.includes(workspace.repoId)) {
      continue
    }
    if (
      filters.workspaceStatuses.length > 0 &&
      (workspace.workspaceStatusId === undefined ||
        !filters.workspaceStatuses.includes(workspace.workspaceStatusId))
    ) {
      continue
    }
    const workspaceSearchText = [workspace.repoName, workspace.worktreeName, workspace.hostLabel]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    const workspaceMatches =
      normalizedQuery.length === 0 || workspaceSearchText.includes(normalizedQuery)
    for (const todo of workspaceTodosForSnapshot(workspace.todos, workspace.worktreeId)) {
      if (workspaceMatches || todo.text.toLowerCase().includes(normalizedQuery)) {
        items.push({ workspace, todo })
      }
    }
  }
  return items
}
