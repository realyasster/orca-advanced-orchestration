import type { CommandHandler } from '../../dispatch'
import { printResult } from '../../format'
import { printOrchestrationResult } from './agent-view'
import {
  getOptionalNonNegativeIntegerFlag,
  getOptionalStringFlag,
  getRequiredStringFlag
} from '../../flags'
import { RuntimeClientError } from '../../runtime-client'
import { readTextOrFileFlag } from '../../command-body-input'
import { callOrchestrationMutation } from './mutation-request'
import { resolveCoordinatorTerminalHandle } from './terminal-identity'

type RunReceipt = {
  run: {
    id: string
    objective: string
    execution_mode?: string
    execution_state?: string | null
    workflow_version?: number
  }
}

const RUN_FIELDS = (r: RunReceipt) => ({
  runId: r.run.id,
  objective: r.run.objective,
  executionMode: r.run.execution_mode,
  executionState: r.run.execution_state ?? undefined,
  workflowVersion: r.run.workflow_version
})

export const ORCHESTRATION_AUTOMATIC_RUN_HANDLERS: Record<string, CommandHandler> = {
  'orchestration workflow-apply': async ({ flags, client, cwd, json }) => {
    const expectedVersion = getOptionalNonNegativeIntegerFlag(flags, 'expected-version')
    if (expectedVersion === undefined) {
      throw new RuntimeClientError('invalid_argument', 'Missing --expected-version')
    }
    const from = await resolveCoordinatorTerminalHandle(flags, cwd, client)
    const result = await callOrchestrationMutation<
      RunReceipt & {
        workflowVersion: number
        created: number
        updated: number
        removed: number
      }
    >(client, flags, 'orchestration.workflowApply', {
      run: getRequiredStringFlag(flags, 'run'),
      workflow: await readTextOrFileFlag(flags, cwd, 'workflow', true),
      expectedVersion,
      from
    })
    if (!flags.has('full')) {
      printOrchestrationResult(result, json, {
        fields: (r) => ({
          ...RUN_FIELDS(r),
          created: r.created,
          updated: r.updated,
          removed: r.removed
        }),
        text: (_, r) =>
          `Workflow v${r.workflowVersion} applied to ${r.run.id}: ${r.created} created, ${r.updated} updated, ${r.removed} removed.`
      })
      return
    }
    printResult(
      result,
      json,
      (r) =>
        `Workflow v${r.workflowVersion} applied to ${r.run.id}: ${r.created} created, ${r.updated} updated, ${r.removed} removed.`
    )
  },

  'orchestration run-start': async ({ flags, client, cwd, json }) => {
    const result = await callOrchestrationMutation<RunReceipt>(
      client,
      flags,
      'orchestration.runStart',
      {
        id: getRequiredStringFlag(flags, 'id'),
        from: await resolveCoordinatorTerminalHandle(flags, cwd, client)
      }
    )
    printOrchestrationResult(result, json, { fields: RUN_FIELDS })
  },

  'orchestration run-resume': async ({ flags, client, cwd, json }) => {
    const result = await callOrchestrationMutation<RunReceipt>(
      client,
      flags,
      'orchestration.runResume',
      {
        id: getRequiredStringFlag(flags, 'id'),
        from: await resolveCoordinatorTerminalHandle(flags, cwd, client)
      }
    )
    printOrchestrationResult(result, json, { fields: RUN_FIELDS })
  },

  'orchestration run-pause': async ({ flags, client, cwd, json }) => {
    const result = await callOrchestrationMutation<RunReceipt>(
      client,
      flags,
      'orchestration.runPause',
      {
        id: getRequiredStringFlag(flags, 'id'),
        reason: getOptionalStringFlag(flags, 'reason'),
        from: await resolveCoordinatorTerminalHandle(flags, cwd, client)
      }
    )
    printOrchestrationResult(result, json, { fields: RUN_FIELDS })
  },

  'orchestration run-cancel': async ({ flags, client, cwd, json }) => {
    const result = await callOrchestrationMutation<RunReceipt>(
      client,
      flags,
      'orchestration.runCancel',
      {
        id: getRequiredStringFlag(flags, 'id'),
        reason: getOptionalStringFlag(flags, 'reason'),
        from: await resolveCoordinatorTerminalHandle(flags, cwd, client)
      }
    )
    printOrchestrationResult(result, json, { fields: RUN_FIELDS })
  }
}
