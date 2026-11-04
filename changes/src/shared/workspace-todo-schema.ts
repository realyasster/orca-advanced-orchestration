import { z } from 'zod'
import { WORKSPACE_TODO_MAX_ITEMS, WORKSPACE_TODO_MAX_TEXT_LENGTH } from './workspace-todo'

export const WorkspaceTodoSchema = z.object({
  id: z.string().min(1),
  workspaceId: z.string().min(1),
  text: z.string().trim().min(1).max(WORKSPACE_TODO_MAX_TEXT_LENGTH),
  createdAt: z.number().finite().nonnegative(),
  updatedAt: z.number().finite().nonnegative(),
  completedAt: z.number().finite().nonnegative().nullable()
})

export const WorkspaceTodosSchema = z.array(WorkspaceTodoSchema).max(WORKSPACE_TODO_MAX_ITEMS)
