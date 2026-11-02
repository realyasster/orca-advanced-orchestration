import { defineMethod } from '../../../core'
import { OrchestrationError } from '../../../../orchestration/orchestration-error'
import {
  RunExecutionCancelParams,
  RunExecutionPauseParams,
  RunExecutionStartParams,
  WorkflowApplyParams
} from '../../../../../../shared/rpc-contract/orchestration-automatic-run-params'
import {
  OrchestrationWorkflow,
  validateOrchestrationWorkflow
} from '../../../../../../shared/orchestration-workflow'
import { resolveRunScope } from '../runs/run-scope'
import { exposeRun } from '../runs/run-receipt'
import { triggerAutomaticRun } from './automatic-run-host'

function requireAutomaticRun(
  runtime: Parameters<typeof triggerAutomaticRun>[0],
  runId: string
): void {
  const run = runtime.getOrchestrationDb().getRun(runId)
  if (!run) {
    throw new OrchestrationError('run_not_found', `Run ${runId} was not found.`)
  }
  if (run.execution_mode !== 'automatic') {
    throw new OrchestrationError(
      'invalid_argument',
      `Run ${runId} is manually operated; automatic controls need --mode automatic at run-create.`
    )
  }
}

export const ORCHESTRATION_AUTOMATIC_RUN_METHODS = [
  defineMethod({
    name: 'orchestration.runStart',
    permission: 'workspace',
    params: RunExecutionStartParams,
    handler: (
      params,
      { runtime, orchestrationCompatibilityEvidence, orchestrationCaller, legacyCoordinatorRunId }
    ) => {
      const run = resolveRunScope(runtime, {
        runId: params.id,
        callerTerminalHandle: params.from,
        requireCurrentConsumer: true,
        legacyCoordinatorRunId,
        callerEvidence: orchestrationCompatibilityEvidence,
        callerSession: orchestrationCaller
      })
      requireAutomaticRun(runtime, run.id)
      const db = runtime.getOrchestrationDb()
      if (db.listTasks({ runId: run.id }).length === 0) {
        throw new OrchestrationError(
          'invalid_argument',
          `Run ${run.id} has no workflow Tasks; apply one with workflow-apply before run-start.`
        )
      }
      if (run.execution_state === 'paused') {
        db.setRunExecutionState(run.id, 'running')
      } else if (run.execution_state === 'preparing') {
        db.setRunExecutionState(run.id, 'running')
      } else if (run.execution_state === 'cancelling') {
        throw new OrchestrationError(
          'run_not_running',
          `Run ${run.id} is cancelling; wait for its stops to settle.`
        )
      } else if (run.execution_state === 'settled') {
        throw new OrchestrationError('run_not_running', `Run ${run.id} has already settled.`)
      }
      const started = db.getRun(run.id) as NonNullable<ReturnType<typeof db.getRun>>
      triggerAutomaticRun(runtime, run.id)
      return { run: exposeRun(started) }
    }
  }),
  defineMethod({
    name: 'orchestration.runPause',
    permission: 'workspace',
    params: RunExecutionPauseParams,
    handler: (
      params,
      { runtime, orchestrationCompatibilityEvidence, orchestrationCaller, legacyCoordinatorRunId }
    ) => {
      const run = resolveRunScope(runtime, {
        runId: params.id,
        callerTerminalHandle: params.from,
        requireCurrentConsumer: true,
        legacyCoordinatorRunId,
        callerEvidence: orchestrationCompatibilityEvidence,
        callerSession: orchestrationCaller
      })
      requireAutomaticRun(runtime, run.id)
      if (run.execution_state === 'running' || run.execution_state === 'preparing') {
        runtime.getOrchestrationDb().setRunExecutionState(run.id, 'paused', {
          pauseReason: params.reason ?? null
        })
      }
      return { run: exposeRun(runtime.getOrchestrationDb().getRun(run.id)!) }
    }
  }),
  defineMethod({
    name: 'orchestration.runResume',
    permission: 'workspace',
    params: RunExecutionStartParams,
    handler: (
      params,
      { runtime, orchestrationCompatibilityEvidence, orchestrationCaller, legacyCoordinatorRunId }
    ) => {
      const run = resolveRunScope(runtime, {
        runId: params.id,
        callerTerminalHandle: params.from,
        requireCurrentConsumer: true,
        legacyCoordinatorRunId,
        callerEvidence: orchestrationCompatibilityEvidence,
        callerSession: orchestrationCaller
      })
      requireAutomaticRun(runtime, run.id)
      if (run.execution_state !== 'paused') {
        throw new OrchestrationError(
          'run_not_running',
          `Run ${run.id} is ${run.execution_state ?? 'not paused'}; only a paused Run resumes.`
        )
      }
      runtime.getOrchestrationDb().setRunExecutionState(run.id, 'running')
      triggerAutomaticRun(runtime, run.id)
      return { run: exposeRun(runtime.getOrchestrationDb().getRun(run.id)!) }
    }
  }),
  defineMethod({
    name: 'orchestration.runCancel',
    permission: 'workspace',
    params: RunExecutionCancelParams,
    handler: (
      params,
      { runtime, orchestrationCompatibilityEvidence, orchestrationCaller, legacyCoordinatorRunId }
    ) => {
      const run = resolveRunScope(runtime, {
        runId: params.id,
        callerTerminalHandle: params.from,
        requireCurrentConsumer: true,
        legacyCoordinatorRunId,
        callerEvidence: orchestrationCompatibilityEvidence,
        callerSession: orchestrationCaller
      })
      requireAutomaticRun(runtime, run.id)
      if (run.execution_state === 'settled') {
        throw new OrchestrationError('run_not_running', `Run ${run.id} has already settled.`)
      }
      runtime.getOrchestrationDb().setRunExecutionState(run.id, 'cancelling', {
        cancelReason: params.reason ?? null
      })
      triggerAutomaticRun(runtime, run.id)
      return { run: exposeRun(runtime.getOrchestrationDb().getRun(run.id)!) }
    }
  }),
  defineMethod({
    name: 'orchestration.workflowApply',
    permission: 'workspace',
    params: WorkflowApplyParams,
    handler: (
      params,
      { runtime, orchestrationCompatibilityEvidence, orchestrationCaller, legacyCoordinatorRunId }
    ) => {
      const run = resolveRunScope(runtime, {
        runId: params.run,
        callerTerminalHandle: params.from,
        requireCurrentConsumer: true,
        legacyCoordinatorRunId,
        callerEvidence: orchestrationCompatibilityEvidence,
        callerSession: orchestrationCaller
      })
      requireAutomaticRun(runtime, run.id)
      let raw: unknown
      try {
        raw = JSON.parse(params.workflow)
      } catch {
        throw new OrchestrationError('invalid_argument', 'Workflow must be valid JSON.')
      }
      const parsed = OrchestrationWorkflow.safeParse(raw)
      if (!parsed.success) {
        throw new OrchestrationError(
          'invalid_argument',
          `Invalid workflow: ${parsed.error.issues.map((issue) => issue.message).join('; ')}`
        )
      }
      const problems = validateOrchestrationWorkflow(parsed.data)
      if (problems.length > 0) {
        throw new OrchestrationError(
          'invalid_argument',
          problems.map((problem) => problem.message).join(' ')
        )
      }
      const applied = runtime.getOrchestrationDb().applyOrchestrationWorkflow({
        runId: run.id,
        expectedVersion: params.expectedVersion,
        workflow: parsed.data
      })
      triggerAutomaticRun(runtime, run.id)
      return {
        run: exposeRun(applied.run),
        workflowVersion: applied.workflowVersion,
        created: applied.created,
        updated: applied.updated,
        removed: applied.removed
      }
    }
  })
]
