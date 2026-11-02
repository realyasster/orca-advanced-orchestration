import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { OrchestrationWorkflow } from '../../../../shared/orchestration-workflow'
import { OrchestrationDb } from '../db/orchestration-db'
import { automaticTaskBrief } from './automatic-run-task-brief'
import type { TaskRow } from '../types'

let db: OrchestrationDb

beforeEach(() => {
  db = new OrchestrationDb(':memory:')
})

afterEach(() => {
  db.close()
})

describe('automaticTaskBrief', () => {
  it('adds direct dependency results, evidence and accepted decisions without rewriting the Task', () => {
    const run = db.createRun({
      objective: 'brief',
      coordinatorHandle: 'term_coord',
      coordinatorPaneKey: 'tab:leaf',
      executionMode: 'automatic',
      workspaceId: 'wt_main'
    })
    db.applyOrchestrationWorkflow({
      runId: run.id,
      expectedVersion: 0,
      workflow: OrchestrationWorkflow.parse({
        tasks: [
          { key: 'A', spec: 'Implement A' },
          { key: 'B', spec: 'Implement B', dependsOn: ['A'] }
        ]
      })
    })
    const a = db.db
      .prepare("SELECT * FROM tasks WHERE run_id = ? AND source_key = 'A'")
      .get(run.id) as TaskRow
    const b = db.db
      .prepare("SELECT * FROM tasks WHERE run_id = ? AND source_key = 'B'")
      .get(run.id) as TaskRow
    db.db
      .prepare("UPDATE tasks SET status = 'completed', resolved_worktree_id = 'wt_a' WHERE id = ?")
      .run(a.id)
    db.recordAutomaticTaskDelivery({
      taskId: a.id,
      runId: run.id,
      outcome: 'succeeded',
      summary: 'A shipped',
      evidence: ['src/a.ts', 'pnpm test a'],
      handoff: 'B can extend A'
    })
    const gate = db.createAutomaticRunGate({
      runId: run.id,
      taskId: a.id,
      question: 'Approach?',
      options: ['yes']
    })
    db.resolveGate(gate.id, 'yes')

    const brief = automaticTaskBrief(db, b)
    expect(brief).toContain('Implement B')
    expect(brief).toContain('A shipped')
    expect(brief).toContain('src/a.ts')
    expect(brief).toContain('B can extend A')
    expect(brief).toContain('Approach? -> yes')
    expect(brief).toContain('wt_a')
    expect(db.getTask(b.id)?.spec).toBe('Implement B')
  })
})
