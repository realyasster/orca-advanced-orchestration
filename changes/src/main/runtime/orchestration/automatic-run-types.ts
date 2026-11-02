export type RunExecutionMode = 'manual' | 'automatic'
export type RunExecutionState = 'preparing' | 'running' | 'paused' | 'cancelling' | 'settled'
export type RunExecutionOutcome = 'completed' | 'failed' | 'cancelled'

export type AutomaticRunEventRow = {
  id: string
  run_id: string
  task_id: string | null
  dispatch_id: string | null
  kind: string
  event_key: string
  payload: string
  state: 'pending' | 'processed' | 'failed'
  attempts: number
  created_at: string
  processed_at: string | null
}

export type AutomaticRunWakeRow = {
  id: string
  run_id: string
  event_id: string
  reason: string
  event_key: string
  status: 'queued' | 'delivered' | 'suppressed'
  message_id: string | null
  created_at: string
  delivered_at: string | null
}
