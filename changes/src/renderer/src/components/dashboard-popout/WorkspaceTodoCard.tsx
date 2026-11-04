import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MoreHorizontal, Trash2 } from 'lucide-react'
import type { DashboardWorkspace } from '../../../../shared/dashboard-snapshot'
import type {
  WorkspaceTodo,
  WorkspaceTodoAction,
  WorkspaceTodoActionResult
} from '../../../../shared/workspace-todo'
import { normalizeWorkspaceTodoText } from '../../../../shared/workspace-todo'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import { translate } from '@/i18n/i18n'
import { cn } from '@/lib/utils'

export type WorkspaceTodoActionHandler = (
  action: WorkspaceTodoAction
) => Promise<WorkspaceTodoActionResult>

function workspaceLabel(workspace: DashboardWorkspace): string {
  return workspace.repoName === workspace.worktreeName
    ? workspace.worktreeName
    : `${workspace.worktreeName} · ${workspace.repoName}`
}

type WorkspaceTodoCardProps = {
  workspace: DashboardWorkspace
  todo: WorkspaceTodo
  pending: boolean
  onTodoAction: WorkspaceTodoActionHandler
  onPendingChange: (todoId: string, pending: boolean) => void
}

/** One manual work item; completion and text edits only publish after the host saves them. */
export function WorkspaceTodoCard({
  workspace,
  todo,
  pending,
  onTodoAction,
  onPendingChange
}: WorkspaceTodoCardProps): React.JSX.Element {
  useTranslation()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(todo.text)
  const [localError, setLocalError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const completed = todo.completedAt !== null

  useEffect(() => {
    if (!editing) {
      setDraft(todo.text)
    }
  }, [editing, todo.text])

  const startEditing = useCallback(() => {
    if (saving) {
      return
    }
    setDraft(todo.text)
    setLocalError(null)
    setEditing(true)
    queueMicrotask(() => inputRef.current?.select())
  }, [saving, todo.text])

  const cancelEditing = useCallback(() => {
    setDraft(todo.text)
    setLocalError(null)
    setEditing(false)
  }, [todo.text])

  const commitText = useCallback(async () => {
    if (saving) {
      return
    }
    const text = normalizeWorkspaceTodoText(draft)
    if (text.length === 0) {
      setLocalError(translate('dashboardPopout.todo.error.invalid', 'Enter a todo before saving.'))
      return
    }
    if (text === todo.text) {
      setEditing(false)
      setLocalError(null)
      return
    }
    setSaving(true)
    try {
      const result = await onTodoAction({
        kind: 'updateText',
        workspaceId: workspace.worktreeId,
        executionHostId: workspace.executionHostId,
        todoId: todo.id,
        text
      })
      if (!result.ok) {
        setLocalError(result.error)
        return
      }
      setEditing(false)
      setLocalError(null)
    } finally {
      setSaving(false)
    }
  }, [draft, onTodoAction, saving, todo.id, todo.text, workspace])

  const toggleCompleted = useCallback(
    async (nextCompleted: boolean) => {
      onPendingChange(todo.id, true)
      setLocalError(null)
      try {
        const result = await onTodoAction({
          kind: 'setCompleted',
          workspaceId: workspace.worktreeId,
          executionHostId: workspace.executionHostId,
          todoId: todo.id,
          completed: nextCompleted
        })
        if (!result.ok) {
          setLocalError(result.error)
        }
      } finally {
        onPendingChange(todo.id, false)
      }
    },
    [onPendingChange, onTodoAction, todo.id, workspace]
  )

  const deleteTodo = useCallback(async () => {
    if (saving) {
      return
    }
    setSaving(true)
    setLocalError(null)
    try {
      const result = await onTodoAction({
        kind: 'delete',
        workspaceId: workspace.worktreeId,
        executionHostId: workspace.executionHostId,
        todoId: todo.id
      })
      if (!result.ok) {
        setLocalError(result.error)
      }
    } finally {
      setSaving(false)
    }
  }, [onTodoAction, saving, todo.id, workspace])

  return (
    <div
      data-testid="todo-card"
      data-todo-id={todo.id}
      data-completed={completed}
      className="group flex w-full flex-col gap-1.5 rounded-lg border border-border/60 bg-card p-2.5 transition-colors hover:border-border hover:bg-accent/40"
    >
      <div className="flex w-full items-start gap-2">
        <Checkbox
          checked={completed}
          disabled={pending || saving}
          onCheckedChange={(checked) => void toggleCompleted(checked === true)}
          aria-label={
            completed
              ? translate('dashboardPopout.todo.reopen', 'Reopen todo')
              : translate('dashboardPopout.todo.complete', 'Mark todo done')
          }
          className="mt-0.5"
        />
        <div className="min-w-0 flex-1">
          {editing ? (
            <Input
              ref={inputRef}
              value={draft}
              disabled={saving}
              data-todo-editor=""
              aria-label={translate('dashboardPopout.todo.edit', 'Edit todo')}
              aria-invalid={localError !== null}
              maxLength={2_000}
              onChange={(event) => setDraft(event.target.value)}
              onBlur={() => void commitText()}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  void commitText()
                } else if (event.key === 'Escape') {
                  event.preventDefault()
                  event.stopPropagation()
                  cancelEditing()
                }
              }}
              className="h-7 bg-background text-xs"
            />
          ) : (
            <button
              type="button"
              onClick={startEditing}
              title={todo.text}
              className={cn(
                'line-clamp-4 w-full text-left text-xs leading-snug break-words focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                completed ? 'text-muted-foreground line-through' : 'text-foreground/90'
              )}
            >
              {todo.text}
            </button>
          )}
          <div className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
            <span className="truncate" title={workspaceLabel(workspace)}>
              {workspaceLabel(workspace)}
            </span>
          </div>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label={translate('dashboardPopout.todo.actions', 'Todo actions')}
              className="text-muted-foreground opacity-70 group-hover:opacity-100"
            >
              <MoreHorizontal className="size-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" sideOffset={4}>
            <DropdownMenuItem variant="destructive" onSelect={() => void deleteTodo()}>
              <Trash2 className="size-3.5" />
              {translate('dashboardPopout.todo.delete', 'Delete todo')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {localError ? (
        <p role="alert" className="text-[11px] leading-snug text-destructive">
          {localError}
        </p>
      ) : null}
    </div>
  )
}
