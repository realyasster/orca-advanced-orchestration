import { z } from 'zod'
import { OptionalString, requiredString } from './rpc-param-primitives'

export const RunExecutionStartParams = z.object({
  id: requiredString('Missing --id'),
  from: OptionalString
})

export const RunExecutionPauseParams = z.object({
  id: requiredString('Missing --id'),
  reason: OptionalString,
  from: OptionalString
})

export const RunExecutionCancelParams = z.object({
  id: requiredString('Missing --id'),
  reason: OptionalString,
  from: OptionalString
})

export const WorkflowApplyParams = z.object({
  run: requiredString('Missing --run'),
  workflow: requiredString('Missing workflow JSON'),
  expectedVersion: z.number().int().min(0),
  from: OptionalString
})
