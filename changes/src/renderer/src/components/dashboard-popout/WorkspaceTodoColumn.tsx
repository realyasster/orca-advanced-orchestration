import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronRight, Plus } from 'lucide-react'
import type { DashboardWorkspace } from '../../../../shared/dashboard-snapshot'
import {
  compareCompletedTodosDesc,
  compareTodosByCreatedAtDesc,
  normalizeWorkspaceTodoText,
  type WorkspaceTodoAction,
  type WorkspaceTodoActionResult
} from '../../../../shared/workspace-todo'
import { createNonSecureContextUuid } from '../../../../shared/non-secure-context-uuid'
import type { DashboardTodoItem } from './workspace-todo-filtering'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { translate } from '@/i18n/i18n'
import { cn } from '@/lib/utils'
import { WorkspaceTodoCard, type WorkspaceTodoActionHandler } from './WorkspaceTodoCard'
import { WorkspaceTodoAddForm } from './WorkspaceTodoAddForm'
import { workspaceTodoValue } from './workspace-todo-presentation'

const UNDO_TIMEOUT_MS = 8_000

type WorkspaceTodoColumnProps = {
  workspaces: readonly DashboardWorkspace[]
  items: readonly DashboardTodoItem[]
  activeWorkspaceId?: string
  activeWorkspaceExecutionHostId?: string
  onTodoAction: WorkspaceTodoActionHandler
}

/** Manual work that never launches agents or enters the agent bucket model. */
export function WorkspaceTodoColumn({
  workspaces,
  items,
  activeWorkspaceId,
  activeWorkspaceExecutionHostId,
  onTodoAction
}: WorkspaceTodoColumnProps): React.JSX.Element {
  useTranslation()
  const supportedWorkspaces = useMemo(
    () => workspaces.filter((workspace) => workspace.todoSupport !== 'unsupported'),
    [workspaces]
  )
  const hasUnsupportedWorkspaces = workspaces.length > 0 && supportedWorkspaces.length === 0
  const activeWorkspace = useMemo(
    () =>
      supportedWorkspaces.find(
        (workspace) =>
          workspace.worktreeId === activeWorkspaceId &&
          (activeWorkspaceExecutionHostId === undefined ||
            workspace.executionHostId === activeWorkspaceExecutionHostId)
      ),
    [activeWorkspaceExecutionHostId, activeWorkspaceId, supportedWorkspaces]
  )
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState('')
  const [selectedWorkspace, setSelectedWorkspace] = useState(
    activeWorkspace ? workspaceTodoValue(activeWorkspace) : ''
  )
  const [formError, setFormError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [pendingTodoIds, setPendingTodoIds] = useState<ReadonlySet<string>>(() => new Set())
  const [deletedTodos, setDeletedTodos] = useState<DashboardTodoItem[]>([])
  const undoTimersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>())
  const createTodoIdRef = useRef<string | null>(null)

  const clearUndoTimer = useCallback((todoId: string) => {
    const timer = undoTimersRef.current.get(todoId)
    if (timer) {
      clearTimeout(timer)
      undoTimersRef.current.delete(todoId)
    }
  }, [])

  useEffect(() => {
    const timers = undoTimersRef.current
    return () => {
      for (const timer of timers.values()) {
        clearTimeout(timer)
      }
      timers.clear()
    }
  }, [])

  useEffect(() => {
    if (!adding) {
      setSelectedWorkspace(activeWorkspace ? workspaceTodoValue(activeWorkspace) : '')
    }
  }, [activeWorkspace, adding])

  const openItems = useMemo(
    () =>
      items
        .filter((item) => item.todo.completedAt === null)
        .slice()
        .sort((a, b) => compareTodosByCreatedAtDesc(a.todo, b.todo)),
    [items]
  )
  const completedItems = useMemo(
    () =>
      items
        .filter((item) => item.todo.completedAt !== null)
        .slice()
        .sort((a, b) => compareCompletedTodosDesc(a.todo, b.todo)),
    [items]
  )

  const setPending = useCallback((todoId: string, pending: boolean) => {
    setPendingTodoIds((current) => {
      const next = new Set(current)
      if (pending) {
        next.add(todoId)
      } else {
        next.delete(todoId)
      }
      return next
    })
  }, [])

  const showDeleted = useCallback(
    (item: DashboardTodoItem) => {
      clearUndoTimer(item.todo.id)
      setDeletedTodos((current) => [
        item,
        ...current.filter((entry) => entry.todo.id !== item.todo.id)
      ])
      undoTimersRef.current.set(
        item.todo.id,
        setTimeout(() => {
          undoTimersRef.current.delete(item.todo.id)
          setDeletedTodos((current) => current.filter((entry) => entry.todo.id !== item.todo.id))
        }, UNDO_TIMEOUT_MS)
      )
    },
    [clearUndoTimer]
  )

  const handleTodoAction = useCallback(
    async (action: WorkspaceTodoAction): Promise<WorkspaceTodoActionResult> => {
      const result = await onTodoAction(action)
      if (result.ok) {
        setActionError(null)
        if (action.kind === 'delete' && result.changed !== false) {
          const item = items.find(
            (candidate) =>
              candidate.workspace.worktreeId === action.workspaceId &&
              candidate.todo.id === action.todoId
          )
          if (item) {
            showDeleted(item)
          }
        }
      }
      return result
    },
    [items, onTodoAction, showDeleted]
  )

  const closeAddForm = useCallback(() => {
    setAdding(false)
    setDraft('')
    setFormError(null)
    createTodoIdRef.current = null
  }, [])

  const openAddForm = useCallback(() => {
    setAdding(true)
    setDraft('')
    setFormError(null)
    setActionError(null)
    createTodoIdRef.current = null
    setSelectedWorkspace(activeWorkspace ? workspaceTodoValue(activeWorkspace) : '')
  }, [activeWorkspace])

  const submitAdd = useCallback(async () => {
    if (saving) {
      return
    }
    const text = normalizeWorkspaceTodoText(draft)
    if (text.length === 0) {
      setFormError(translate('dashboardPopout.todo.error.invalid', 'Enter a todo before saving.'))
      return
    }
    const workspace = supportedWorkspaces.find(
      (candidate) => workspaceTodoValue(candidate) === selectedWorkspace
    )
    if (!workspace) {
      setFormError(
        translate('dashboardPopout.todo.error.workspace', 'Choose a workspace for this todo.')
      )
      return
    }
    setSaving(true)
    setFormError(null)
    // Reuse one id across retries so an IPC timeout cannot create a duplicate todo.
    createTodoIdRef.current ??= createNonSecureContextUuid()
    try {
      const result = await onTodoAction({
        kind: 'create',
        workspaceId: workspace.worktreeId,
        executionHostId: workspace.executionHostId,
        text,
        todoId: createTodoIdRef.current
      })
      if (!result.ok) {
        setFormError(result.error)
        return
      }
      createTodoIdRef.current = null
      setAdding(false)
      setDraft('')
      setActionError(null)
    } finally {
      setSaving(false)
    }
  }, [draft, onTodoAction, saving, selectedWorkspace, supportedWorkspaces])

  const undoDelete = useCallback(async () => {
    const item = deletedTodos[0]
    if (!item) {
      return
    }
    setPending(item.todo.id, true)
    const result = await onTodoAction({
      kind: 'restore',
      workspaceId: item.workspace.worktreeId,
      executionHostId: item.workspace.executionHostId,
      todo: item.todo
    })
    setPending(item.todo.id, false)
    if (!result.ok) {
      setActionError(result.error)
      return
    }
    clearUndoTimer(item.todo.id)
    setDeletedTodos((current) => current.filter((entry) => entry.todo.id !== item.todo.id))
    setActionError(null)
  }, [clearUndoTimer, deletedTodos, onTodoAction, setPending])

  return (
    <section
      aria-label={translate('dashboardPopout.todo.title', 'Todo')}
      className="flex min-w-[264px] flex-1 flex-col rounded-xl border border-border/60 bg-muted/30"
    >
      <header className="flex items-center gap-2 px-3 py-2">
        <span className="text-[11px] font-semibold tracking-[0.05em] text-muted-foreground uppercase">
          {translate('dashboardPopout.todo.title', 'Todo')}
        </span>
        <span className="ml-auto rounded-full bg-background px-1.5 text-[11px] tabular-nums text-muted-foreground">
          {openItems.length}
        </span>
        {!adding && supportedWorkspaces.length > 0 ? (
          <Button
            variant="ghost"
            size="xs"
            onClick={openAddForm}
            disabled={hasUnsupportedWorkspaces}
            className="gap-1 px-1.5 text-[11px] text-muted-foreground hover:text-foreground"
            aria-label={translate('dashboardPopout.todo.add', 'Add todo')}
          >
            <Plus className="size-3" />
            {translate('dashboardPopout.todo.addLabel', 'Add')}
          </Button>
        ) : null}
      </header>
      <div className="scrollbar-sleek flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-2 pb-2">
        {hasUnsupportedWorkspaces ? (
          <p role="status" className="px-1 py-2 text-[11px] text-muted-foreground">
            {translate(
              'dashboardPopout.todo.error.unsupported',
              'This host does not support workspace todos.'
            )}
          </p>
        ) : null}
        {!hasUnsupportedWorkspaces && adding ? (
          <WorkspaceTodoAddForm
            workspaces={supportedWorkspaces}
            draft={draft}
            onDraftChange={setDraft}
            selectedWorkspace={selectedWorkspace}
            onWorkspaceChange={(value) => {
              // A client id names one workspace list; never reuse it after switching targets.
              createTodoIdRef.current = null
              setSelectedWorkspace(value)
              setFormError(null)
            }}
            error={formError}
            saving={saving}
            onSubmit={() => void submitAdd()}
            onCancel={closeAddForm}
          />
        ) : null}
        {actionError ? (
          <p role="alert" className="px-1 text-[11px] leading-snug text-destructive">
            {actionError}
          </p>
        ) : null}
        {openItems.length === 0 && !adding && !hasUnsupportedWorkspaces ? (
          <p className="px-1 py-2 text-[11px] text-muted-foreground">
            {translate('dashboardPopout.todo.empty', 'No open todos')}
          </p>
        ) : (
          openItems.map((item) => (
            <WorkspaceTodoCard
              key={item.todo.id}
              workspace={item.workspace}
              todo={item.todo}
              pending={pendingTodoIds.has(item.todo.id)}
              onTodoAction={handleTodoAction}
              onPendingChange={setPending}
            />
          ))
        )}
        {completedItems.length > 0 ? (
          <Collapsible defaultOpen={false} className="mt-1">
            <CollapsibleTrigger asChild>
              <button
                type="button"
                className="group flex w-full items-center gap-1 rounded-md px-1 py-1 text-left text-[11px] text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                <ChevronRight className="size-3 transition-transform group-data-[state=open]:rotate-90" />
                {translate('dashboardPopout.todo.completed', 'Completed')}
                <span className="tabular-nums">({completedItems.length})</span>
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent className="flex flex-col gap-2 pt-2">
              {completedItems.map((item) => (
                <WorkspaceTodoCard
                  key={item.todo.id}
                  workspace={item.workspace}
                  todo={item.todo}
                  pending={pendingTodoIds.has(item.todo.id)}
                  onTodoAction={handleTodoAction}
                  onPendingChange={setPending}
                />
              ))}
            </CollapsibleContent>
          </Collapsible>
        ) : null}
        {deletedTodos.length > 0 ? (
          <div
            role="status"
            className={cn(
              'mt-auto flex items-center justify-between gap-2 rounded-md border border-border/60 bg-background px-2 py-1.5 text-[11px] text-muted-foreground'
            )}
          >
            <span className="truncate">
              {deletedTodos.length === 1
                ? translate('dashboardPopout.todo.deleted', 'Todo deleted.')
                : translate('dashboardPopout.todo.deletedCount', '{{count}} todos deleted.', {
                    count: deletedTodos.length
                  })}
            </span>
            <button
              type="button"
              onClick={() => void undoDelete()}
              className="shrink-0 rounded-sm font-medium text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              {translate('dashboardPopout.todo.undo', 'Undo')}
            </button>
          </div>
        ) : null}
      </div>
    </section>
  )
}
