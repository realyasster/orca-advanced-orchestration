import type { DashboardWorkspace } from '../../../../shared/dashboard-snapshot'

const WORKSPACE_VALUE_SEPARATOR = '\u001f'

/** Host-qualified value keeps same-id workspaces on different hosts distinct in the picker. */
export function workspaceTodoValue(workspace: DashboardWorkspace): string {
  return `${workspace.executionHostId}${WORKSPACE_VALUE_SEPARATOR}${workspace.worktreeId}`
}

export function workspaceTodoLabel(workspace: DashboardWorkspace): string {
  return workspace.repoName === workspace.worktreeName
    ? workspace.worktreeName
    : `${workspace.worktreeName} · ${workspace.repoName}`
}
