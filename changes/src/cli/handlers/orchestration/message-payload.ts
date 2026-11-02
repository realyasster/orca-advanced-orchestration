import { getOptionalJsonFlag, getOptionalStringFlag } from '../../flags'
import { RuntimeClientError } from '../../runtime-client'

export function getOptionalStructuredMessagePayload(
  flags: Map<string, string | boolean>
): string | undefined {
  const rawPayload = getOptionalJsonFlag(flags, 'payload')
  const taskId = getOptionalStringFlag(flags, 'task-id')
  const dispatchId = getOptionalStringFlag(flags, 'dispatch-id')
  const outcome = getOptionalStringFlag(flags, 'outcome')
  const filesModified = getOptionalStringFlag(flags, 'files-modified')
  const reportPath = getOptionalStringFlag(flags, 'report-path')
  const phase = getOptionalStringFlag(flags, 'phase')
  const summary = getOptionalStringFlag(flags, 'summary')
  const evidence = getOptionalStringFlag(flags, 'evidence')
  const handoff = getOptionalStringFlag(flags, 'handoff')
  const reviewVerdict = getOptionalStringFlag(flags, 'review-verdict')
  const hasStructuredPayload =
    taskId !== undefined ||
    dispatchId !== undefined ||
    outcome !== undefined ||
    filesModified !== undefined ||
    reportPath !== undefined ||
    phase !== undefined ||
    summary !== undefined ||
    evidence !== undefined ||
    handoff !== undefined ||
    reviewVerdict !== undefined
  if (!hasStructuredPayload) {
    return rawPayload
  }
  if (rawPayload !== undefined) {
    throw new RuntimeClientError(
      'invalid_argument',
      'Use either --payload or structured payload flags, not both.'
    )
  }
  // Structured flags avoid fragile PowerShell JSON quoting.
  const payload: Record<string, string | string[]> = {}
  if (taskId) {
    payload.taskId = taskId
  }
  if (dispatchId) {
    payload.dispatchId = dispatchId
  }
  if (outcome) {
    if (outcome !== 'succeeded' && outcome !== 'failed') {
      throw new RuntimeClientError(
        'invalid_argument',
        'Invalid --outcome. Expected succeeded or failed.'
      )
    }
    payload.outcome = outcome
  }
  if (filesModified) {
    payload.filesModified = filesModified
      .split(',')
      .map((file) => file.trim())
      .filter(Boolean)
  }
  if (reportPath) {
    payload.reportPath = reportPath
  }
  if (phase) {
    payload.phase = phase
  }
  if (summary) {
    payload.summary = summary
  }
  if (evidence) {
    payload.evidence = evidence
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
  }
  if (handoff) {
    payload.handoff = handoff
  }
  if (reviewVerdict) {
    if (reviewVerdict !== 'approved' && reviewVerdict !== 'changes_requested') {
      throw new RuntimeClientError(
        'invalid_argument',
        'Invalid --review-verdict. Expected approved or changes_requested.'
      )
    }
    payload.reviewVerdict = reviewVerdict
  }
  return JSON.stringify(payload)
}
