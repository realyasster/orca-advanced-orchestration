export type LegacyAdoptionRow = {
  source_run_id: string
  adopted_run_id: string
  scheduler_state_lost: number
  adopted_at: string
}

export type LegacyPrincipalRole = 'worker' | 'coordinator'

export type LegacyPrincipalStatus = 'committed' | 'settled' | 'revoked'

export type LegacyCompatibilityPrincipalRow = {
  id: string
  run_id: string
  dispatch_id: string | null
  role: LegacyPrincipalRole
  host_scope: string
  terminal_handle: string
  pane_key: string
  launch_token_hash: string
  process_incarnation: string | null
  status: LegacyPrincipalStatus
}

export type LegacyOperationReceiptRow = {
  principal_id: string
  operation_key: string
  method: string
  payload_hash: string
  effect_id: string
  response_json: string
  completed_at: string
}

export type LegacyMailReceiptRow = {
  principal_id: string
  message_id: string
  acknowledged_at: string | null
}
