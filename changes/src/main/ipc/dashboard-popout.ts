import { app, ipcMain } from 'electron'
import { randomUUID } from 'node:crypto'
import type { Store } from '../persistence/loading-store/store'
import type { KeybindingService } from '../keybindings/keybinding-service'
import type { DashboardSnapshot } from '../../shared/dashboard-snapshot'
import {
  isWorkspaceTodoAction,
  isWorkspaceTodoActionErrorCode,
  type WorkspaceTodoActionResult,
  type WorkspaceTodoRelayResponse
} from '../../shared/workspace-todo'
import {
  createOrFocusDashboardPopout,
  closeDashboardPopout,
  getDashboardPopoutWindow,
  isDashboardPopoutRenderer,
  onDashboardPopoutOpenChanged
} from '../window/dashboard-popout-window'
import { safelyRevealWindow } from '../window/focus-existing-window'
import { isBackgroundLaunch } from '../window/foreground-activation-policy'
import { getTrustedUIRendererWindow, isTrustedUIRenderer, sendToTrustedUIRenderer } from './ui'
import {
  admitDashboardSnapshot,
  isDashboardPaneKey,
  isDashboardRevealAgentArgs
} from './dashboard-payload-validation'

// Replay immediately on mount; clear on close to avoid showing a previous session.
let lastSnapshot: DashboardSnapshot | null = null

let disposePopoutOpenChanged: (() => void) | null = null
let disposeSettingsChanged: (() => void) | null = null

const TODO_ACTION_TIMEOUT_MS = 10_000
const pendingTodoActions = new Map<
  string,
  {
    resolve: (result: WorkspaceTodoActionResult) => void
    timer: ReturnType<typeof setTimeout>
  }
>()

function settleTodoAction(requestId: string, result: WorkspaceTodoActionResult): void {
  const pending = pendingTodoActions.get(requestId)
  if (!pending) {
    return
  }
  clearTimeout(pending.timer)
  pendingTodoActions.delete(requestId)
  pending.resolve(result)
}

function failPendingTodoActions(message: string): void {
  for (const requestId of pendingTodoActions.keys()) {
    settleTodoAction(requestId, { ok: false, code: 'save-failed', error: message })
  }
}

function isDashboardEnabled(store: Store): boolean {
  return store.getSettings().experimentalAgentDashboardPopout === true
}

export function registerDashboardPopoutHandlers(
  store: Store,
  keybindings?: KeybindingService
): void {
  ipcMain.removeHandler('dashboardPopout:open')
  ipcMain.removeHandler('dashboard:publishSnapshot')
  ipcMain.removeHandler('dashboard:requestSnapshot')
  ipcMain.removeHandler('dashboard:getPopoutOpen')
  ipcMain.removeHandler('dashboardPopout:revealAgent')
  ipcMain.removeHandler('dashboardPopout:ackAgent')
  ipcMain.removeHandler('dashboardPopout:todoAction')
  ipcMain.removeHandler('dashboardPopout:todoActionResult')

  disposePopoutOpenChanged?.()
  disposePopoutOpenChanged = onDashboardPopoutOpenChanged((open) => {
    if (!open) {
      lastSnapshot = null
      failPendingTodoActions('The dashboard was closed before the todo was saved.')
    }
  })
  disposeSettingsChanged?.()
  disposeSettingsChanged = store.onSettingsChanged((updates, settings) => {
    if (
      'experimentalAgentDashboardPopout' in updates &&
      settings.experimentalAgentDashboardPopout !== true
    ) {
      lastSnapshot = null
      closeDashboardPopout()
    }
  })

  ipcMain.handle('dashboardPopout:open', (event): void => {
    if (!isTrustedUIRenderer(event.sender) || !isDashboardEnabled(store)) {
      return
    }
    createOrFocusDashboardPopout(store, {
      getKeybindings: () => keybindings?.getOverrides()
    })
  })

  ipcMain.handle('dashboard:publishSnapshot', (event, snapshot: unknown): void => {
    if (!isTrustedUIRenderer(event.sender) || !isDashboardEnabled(store)) {
      return
    }
    const admitted = admitDashboardSnapshot(snapshot)
    // Explain stale replays instead of silently discarding malformed snapshots.
    if (!admitted) {
      console.warn('[dashboard] rejected malformed snapshot; pop-out keeps its previous board')
      return
    }
    if (admitted.droppedCardCount > 0) {
      console.warn(`[dashboard] dropped ${admitted.droppedCardCount} invalid card(s) from snapshot`)
    }
    // Retain omitted unchanged icons for newly mounting popouts; live forwards stay sparse.
    lastSnapshot =
      admitted.snapshot.repoIconsByRepoId === undefined && lastSnapshot?.repoIconsByRepoId
        ? { ...admitted.snapshot, repoIconsByRepoId: lastSnapshot.repoIconsByRepoId }
        : admitted.snapshot
    getDashboardPopoutWindow()?.webContents.send('dashboard:snapshot', admitted.snapshot)
  })

  // Replay immediately, then request fresh renderer state.
  ipcMain.handle('dashboard:requestSnapshot', (event): void => {
    if (!isDashboardPopoutRenderer(event.sender) || !isDashboardEnabled(store)) {
      return
    }
    if (lastSnapshot) {
      event.sender.send('dashboard:snapshot', lastSnapshot)
    }
    sendToTrustedUIRenderer('dashboard:snapshotRequested', null)
  })

  ipcMain.handle('dashboard:getPopoutOpen', (event): boolean =>
    isTrustedUIRenderer(event.sender) && isDashboardEnabled(store)
      ? getDashboardPopoutWindow() !== null
      : false
  )

  // Acknowledge in the main store so popout views also mute sidebar rows.
  ipcMain.handle('dashboardPopout:ackAgent', (event, args: unknown): void => {
    const ack = args && typeof args === 'object' ? args : {}
    const paneKey = 'paneKey' in ack ? ack.paneKey : undefined
    if (
      !isDashboardPopoutRenderer(event.sender) ||
      !isDashboardEnabled(store) ||
      !isDashboardPaneKey(paneKey)
    ) {
      return
    }
    sendToTrustedUIRenderer('ui:ackDashboardAgent', {
      paneKey,
      intent: 'intent' in ack && ack.intent === 'explicit' ? 'explicit' : 'view'
    })
  })

  // Pop-out mutations wait for the main window's persistence result instead of assuming success.
  ipcMain.handle(
    'dashboardPopout:todoAction',
    (event, action: unknown): Promise<WorkspaceTodoActionResult> => {
      if (
        !isDashboardPopoutRenderer(event.sender) ||
        !isDashboardEnabled(store) ||
        !isWorkspaceTodoAction(action)
      ) {
        return Promise.resolve({
          ok: false,
          code: 'invalid',
          error: 'This todo change is not valid.'
        })
      }
      const mainWindow = getTrustedUIRendererWindow()
      if (!mainWindow) {
        return Promise.resolve({
          ok: false,
          code: 'save-failed',
          error: 'The Orca window is not available.'
        })
      }
      const requestId = randomUUID()
      return new Promise((resolve) => {
        const timer = setTimeout(() => {
          settleTodoAction(requestId, {
            ok: false,
            code: 'save-failed',
            error: 'Saving the todo timed out. Try again.'
          })
        }, TODO_ACTION_TIMEOUT_MS)
        pendingTodoActions.set(requestId, { resolve, timer })
        mainWindow.webContents.send('ui:dashboardTodoAction', { requestId, action })
      })
    }
  )

  ipcMain.handle('dashboardPopout:todoActionResult', (event, response: unknown): void => {
    if (!isTrustedUIRenderer(event.sender) || !response || typeof response !== 'object') {
      return
    }
    const relay = response as Partial<WorkspaceTodoRelayResponse>
    if (typeof relay.requestId !== 'string' || !relay.result) {
      return
    }
    if (relay.result.ok === true) {
      settleTodoAction(
        relay.requestId,
        relay.result.changed === false ? { ok: true, changed: false } : { ok: true, changed: true }
      )
      return
    }
    if (
      relay.result.ok === false &&
      typeof relay.result.error === 'string' &&
      isWorkspaceTodoActionErrorCode(relay.result.code)
    ) {
      settleTodoAction(relay.requestId, {
        ok: false,
        code: relay.result.code,
        error: relay.result.error
      })
    }
  })

  ipcMain.handle('dashboardPopout:revealAgent', (event, args: unknown): void => {
    if (
      !isDashboardPopoutRenderer(event.sender) ||
      !isDashboardEnabled(store) ||
      !isDashboardRevealAgentArgs(args)
    ) {
      return
    }
    const mainWindow = getTrustedUIRendererWindow()
    if (!mainWindow) {
      return
    }
    safelyRevealWindow(mainWindow)
    mainWindow.webContents.send('ui:revealDashboardAgent', args)
    if (!isBackgroundLaunch()) {
      try {
        app.focus({ steal: true })
      } catch {
        // Best-effort; the per-window focus above may still bring it forward.
      }
    }
  })
}
