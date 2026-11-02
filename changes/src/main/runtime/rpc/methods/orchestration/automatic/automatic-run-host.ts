import type { OrcaRuntimeService } from '../../../../orca-runtime'
import type { OrchestrationDb } from '../../../../orchestration/db'
import type { RunRow, TaskRow } from '../../../../orchestration/types'
import {
  AutomaticRunExecutor,
  type AutomaticLaunchRequest,
  type AutomaticLaunchResult,
  type AutomaticRunHost
} from '../../../../orchestration/automatic-run/automatic-run-executor'
import { currentRunCoordinatorOrcaSessionId } from '../../../../orchestration/db/runs/run-coordinator-orca-session'
import {
  mailboxAddressOf,
  type OrchestrationSessionCaller
} from '../../../../orchestration/orchestration-caller-identity'
import { startLocalWorker } from '../worker/local-worker-start'
import { automaticTaskBrief } from '../../../../orchestration/automatic-run/automatic-run-task-brief'
import { getActiveDispatchForTask } from '../../../../orchestration/db/dispatch-context/task-dispatch-reconciliation'
import { recordAutomaticRunEvent } from '../../../../orchestration/db/automatic-runs/automatic-run-store'
import {
  decideWorkerStartMode,
  readWorkerStartModeSettings
} from '../../orchestration-worker-start-mode'
import { WorkerStartParams } from '../../../../../../shared/rpc-contract/orchestration-worker-start-params'
import { ORCHESTRATION_WORKER_STOP_METHODS } from '../worker/worker-stop'

const executors = new WeakMap<OrcaRuntimeService, AutomaticRunExecutor>()

export function getAutomaticRunExecutor(runtime: OrcaRuntimeService): AutomaticRunExecutor {
  let executor = executors.get(runtime)
  if (!executor) {
    executor = new AutomaticRunExecutor(
      runtime.getOrchestrationDb(),
      createAutomaticRunHost(runtime)
    )
    executors.set(runtime, executor)
  }
  return executor
}

export function triggerAutomaticRun(runtime: OrcaRuntimeService, runId: string): void {
  getAutomaticRunExecutor(runtime).trigger(runId)
}

/** Called when the runtime opens its orchestration database. */
export function recoverAutomaticRuns(runtime: OrcaRuntimeService): void {
  getAutomaticRunExecutor(runtime).recover()
}

function createAutomaticRunHost(runtime: OrcaRuntimeService): AutomaticRunHost {
  return {
    launchTask: (request) => launchAutomaticTask(runtime, request),
    stopDispatch: (dispatchId) => stopAutomaticDispatch(runtime, dispatchId),
    notifyRun: (runId) => runtime.notifyMessageArrived(`run:${runId}`, 'decision_gate')
  }
}

export async function launchAutomaticTask(
  runtime: OrcaRuntimeService,
  request: AutomaticLaunchRequest
): Promise<AutomaticLaunchResult> {
  const db = runtime.getOrchestrationDb()
  const { run, task, options } = request
  const agent = options.agent ?? defaultAgent(runtime)
  const orcaSessionId = currentRunCoordinatorOrcaSessionId(run)
  const coordinatorIdentity = {
    terminalHandle: run.coordinator_handle,
    paneKey: run.coordinator_pane_key,
    orcaSessionId
  }
  const address = mailboxAddressOf(coordinatorIdentity) ?? run.coordinator_handle ?? 'orca:auto'
  const coordinator = { ...coordinatorIdentity, address }
  const params = WorkerStartParams.parse({
    task: task.id,
    run: run.id,
    from: address,
    ...(request.worktree ? { worktree: request.worktree } : {}),
    ...(agent ? { agent } : {}),
    ...(options.model ? { model: options.model } : {}),
    ...(options.effort ? { effort: options.effort } : {}),
    ...(options.timeoutMs ? { timeoutMs: options.timeoutMs } : {})
  })
  // A structured coordinator is identified by its session id, not by declaring a chat address.
  const callerSession: OrchestrationSessionCaller | undefined =
    orcaSessionId && run.workspace_id
      ? {
          ...coordinator,
          address,
          orcaSessionId,
          sessionId: orcaSessionId,
          workspaceId: run.workspace_id
        }
      : undefined
  const mode = decideWorkerStartMode({
    params,
    settings: readWorkerStartModeSettings(runtime)
  })
  try {
    const receipt = await startLocalWorker({
      params,
      runtime,
      db,
      bindRun: () => run,
      taskDeps: undefined,
      coordinator,
      callerSession,
      existingTask: { ...task, spec: automaticTaskBrief(db, task) },
      mode,
      ...(run.workspace_id ? { workspaceIdOverride: run.workspace_id } : {})
    })
    return launchReceipt(receipt, db, task)
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    // Acceptance may have committed before the response was lost; never start a second worker.
    const active = getActiveDispatchForTask(db, task.id)
    if (active) {
      recordAutomaticRunEvent.call(db, {
        runId: run.id,
        kind: 'launch_unknown',
        eventKey: `launch_unknown:${active.id}`,
        taskId: task.id,
        dispatchId: active.id,
        payload: { error: message }
      })
      return { dispatchId: active.id }
    }
    return { error: message }
  }
}

function launchReceipt(
  receipt: unknown,
  db: OrchestrationDb,
  task: TaskRow
): AutomaticLaunchResult {
  if (receipt && typeof receipt === 'object') {
    const record = receipt as {
      dispatchId?: unknown
      worktree?: { id?: unknown }
      state?: unknown
      error?: unknown
    }
    if (typeof record.dispatchId === 'string') {
      const worker = db.getWorkerDispatch(record.dispatchId)
      if (worker?.state === 'ready' || worker?.state === 'starting') {
        return {
          dispatchId: record.dispatchId,
          ...(typeof record.worktree?.id === 'string' ? { worktreeId: record.worktree.id } : {})
        }
      }
    }
    if (record.state === 'failed' || typeof record.error === 'string') {
      return { error: typeof record.error === 'string' ? record.error : 'worker launch failed' }
    }
  }
  return { error: `Worker launch for Task ${task.id} returned no Dispatch.` }
}

async function stopAutomaticDispatch(
  runtime: OrcaRuntimeService,
  dispatchId: string
): Promise<{ state: string; stopped: boolean; reason?: string }> {
  const method = ORCHESTRATION_WORKER_STOP_METHODS[0]
  // SAFETY: the stop handler reads only `runtime` and the optional mutation receipt.
  const handler = method.handler as unknown as (
    params: { dispatch: string },
    context: { runtime: OrcaRuntimeService; orchestrationMutation: undefined }
  ) => Promise<unknown>
  try {
    const receipt = await handler(
      { dispatch: dispatchId },
      { runtime, orchestrationMutation: undefined }
    )
    if (receipt && typeof receipt === 'object') {
      const record = receipt as { state?: unknown; alreadySettled?: unknown; warning?: unknown }
      const state = typeof record.state === 'string' ? record.state : 'unknown'
      if (state === 'stopped' || state === 'succeeded' || state === 'failed') {
        return { state, stopped: true }
      }
      return {
        state,
        stopped: false,
        reason:
          typeof record.warning === 'string'
            ? record.warning
            : 'The worker stop outcome could not be proven.'
      }
    }
    return { state: 'unknown', stopped: false, reason: 'No stop receipt was returned.' }
  } catch (error) {
    return {
      state: 'stop_unknown',
      stopped: false,
      reason: error instanceof Error ? error.message : String(error)
    }
  }
}

function defaultAgent(runtime: OrcaRuntimeService): string | undefined {
  try {
    const settings = runtime.getClientSettings() as { defaultTuiAgent?: string | null } | null
    const agent = settings?.defaultTuiAgent
    return agent && agent !== 'blank' ? agent : undefined
  } catch {
    return undefined
  }
}

export type { RunRow }
