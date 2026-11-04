import { describe, expect, it } from 'vitest'
import { buildDashboardSnapshot, type DashboardSnapshotInput } from './build-dashboard-snapshot'
import type { TerminalTab } from '../../../../shared/terminal-tab-types'
import type { Worktree } from '../../../../shared/worktree/types'
import { createWorkspaceTodo } from '../../../../shared/workspace-todo'

const NOW = 1_000_000_000
const TAB_ID = 'tab1'
const LEAF_ID = '11111111-1111-4111-8111-111111111111'

function tab(): TerminalTab {
  return {
    id: TAB_ID,
    ptyId: 'pty1',
    worktreeId: 'w1',
    title: 'agent',
    customTitle: null,
    color: null,
    sortOrder: 0,
    createdAt: NOW
  }
}

function worktree(todos: Worktree['todos']): Worktree {
  return {
    id: 'w1',
    repoId: 'r1',
    path: '/r1/w1',
    head: 'abc123',
    branch: 'main',
    isBare: false,
    isMainWorktree: false,
    displayName: 'wt-one',
    comment: '',
    linkedIssue: null,
    linkedPR: null,
    linkedLinearIssue: null,
    isArchived: false,
    isUnread: false,
    isPinned: false,
    sortOrder: 0,
    lastActivityAt: NOW,
    todos
  }
}

function state(todos: Worktree['todos']): DashboardSnapshotInput {
  return {
    chatNames: new Map(),
    repos: [{ id: 'r1', path: '/r1', displayName: 'Repo One', badgeColor: '#000', addedAt: NOW }],
    worktreesByRepo: { r1: [worktree(todos)] },
    tabsByWorktree: { w1: [tab()] },
    agentStatusByPaneKey: {},
    retainedAgentsByPaneKey: {},
    migrationUnsupportedByPtyId: {},
    runtimeAgentOrchestrationByPaneKey: {},
    terminalLayoutsByTabId: {
      [TAB_ID]: {
        root: { type: 'leaf', leafId: LEAF_ID },
        activeLeafId: LEAF_ID,
        expandedLeafId: null,
        ptyIdsByLeafId: { [LEAF_ID]: 'pty1' }
      }
    },
    ptyIdsByTabId: { [TAB_ID]: ['pty1'] },
    runtimePaneTitlesByTabId: {},
    acknowledgedAgentsByPaneKey: {},
    settings: null,
    activeWorktreeId: 'w1',
    activeWorkspaceExecutionHostId: 'local'
  }
}

describe('buildDashboardSnapshot todos', () => {
  const todos = [createWorkspaceTodo({ workspaceId: 'w1', text: 'Manual work', now: 100 })]

  it('publishes workspace todos and the active workspace identity', () => {
    const snapshot = buildDashboardSnapshot(state(todos), NOW)

    expect(snapshot.activeWorkspaceId).toBe('w1')
    expect(snapshot.activeWorkspaceExecutionHostId).toBe('local')
    expect(snapshot.workspaces?.[0]?.todos).toEqual(todos)
    expect(snapshot.workspaces?.[0]?.todoSupport).toBe('supported')
  })

  it('omits todo projection from count-only snapshots', () => {
    const snapshot = buildDashboardSnapshot(state(todos), NOW, { includeCardDetails: false })

    expect(snapshot.workspaces).toBeUndefined()
  })
})
