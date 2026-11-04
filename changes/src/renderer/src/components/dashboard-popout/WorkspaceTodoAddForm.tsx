import { useTranslation } from 'react-i18next'
import type { DashboardWorkspace } from '../../../../shared/dashboard-snapshot'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select'
import { translate } from '@/i18n/i18n'
import { workspaceTodoLabel, workspaceTodoValue } from './workspace-todo-presentation'

type WorkspaceTodoAddFormProps = {
  workspaces: readonly DashboardWorkspace[]
  draft: string
  onDraftChange: (value: string) => void
  selectedWorkspace: string
  onWorkspaceChange: (value: string) => void
  error: string | null
  saving: boolean
  onSubmit: () => void
  onCancel: () => void
}

export function WorkspaceTodoAddForm({
  workspaces,
  draft,
  onDraftChange,
  selectedWorkspace,
  onWorkspaceChange,
  error,
  saving,
  onSubmit,
  onCancel
}: WorkspaceTodoAddFormProps): React.JSX.Element {
  useTranslation()
  return (
    <form
      data-todo-add-form=""
      className="flex flex-col gap-1.5 rounded-lg border border-border/60 bg-card p-2"
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit()
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault()
          event.stopPropagation()
          onCancel()
        }
      }}
    >
      <Input
        value={draft}
        onChange={(event) => onDraftChange(event.target.value)}
        placeholder={translate('dashboardPopout.todo.placeholder', 'What needs doing?')}
        aria-label={translate('dashboardPopout.todo.input', 'New todo')}
        aria-invalid={error !== null}
        maxLength={2_000}
        disabled={saving}
        autoFocus
        className="h-7 bg-background text-xs"
      />
      <Select value={selectedWorkspace} onValueChange={onWorkspaceChange} disabled={saving}>
        <SelectTrigger
          size="sm"
          aria-label={translate('dashboardPopout.todo.workspace', 'Todo workspace')}
          className="h-7 w-full text-xs"
        >
          <SelectValue
            placeholder={translate(
              'dashboardPopout.todo.workspacePlaceholder',
              'Choose a workspace'
            )}
          />
        </SelectTrigger>
        <SelectContent position="popper" className="max-w-[320px]">
          {workspaces.map((workspace) => (
            <SelectItem key={workspaceTodoValue(workspace)} value={workspaceTodoValue(workspace)}>
              {workspaceTodoLabel(workspace)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {error ? (
        <p role="alert" className="text-[11px] leading-snug text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex items-center justify-end gap-1">
        <Button type="button" variant="ghost" size="xs" onClick={onCancel} disabled={saving}>
          {translate('dashboardPopout.todo.cancel', 'Cancel')}
        </Button>
        <Button
          type="submit"
          size="xs"
          disabled={saving || draft.trim().length === 0 || selectedWorkspace.length === 0}
        >
          {saving
            ? translate('dashboardPopout.todo.saving', 'Saving…')
            : translate('dashboardPopout.todo.save', 'Save')}
        </Button>
      </div>
    </form>
  )
}
