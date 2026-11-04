import type { RuntimeClientTarget } from '../../../shared/runtime-client-target'
import { WORKSPACE_TODO_RUNTIME_CAPABILITY } from '../../../shared/worktree-runtime-capabilities'
import { assertRuntimeEnvironmentCapability } from './runtime-rpc-client'

/** Older remote hosts strip unknown metadata, so refuse todo writes before they look successful. */
export async function assertWorkspaceTodoWriteCapability(
  target: RuntimeClientTarget
): Promise<void> {
  if (target.kind !== 'environment') {
    return
  }
  await assertRuntimeEnvironmentCapability(
    target.environmentId,
    WORKSPACE_TODO_RUNTIME_CAPABILITY,
    'This host does not support workspace todos.'
  )
}
