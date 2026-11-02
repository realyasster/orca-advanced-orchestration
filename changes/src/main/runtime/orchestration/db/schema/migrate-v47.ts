import type { OrchestrationDb } from '../orchestration-db'

/** Automatic Runs: opt-in execution metadata, per-Task scheduling/delivery, the event outbox and wake ledger. */
export function migrateV47(this: OrchestrationDb, current: number): void {
  if (current >= 47) {
    return
  }
  addColumn(this, 'runs', 'execution_mode', "TEXT NOT NULL DEFAULT 'manual'")
  addColumn(this, 'runs', 'execution_state', 'TEXT')
  addColumn(this, 'runs', 'execution_outcome', 'TEXT')
  addColumn(this, 'runs', 'max_parallel', 'INTEGER NOT NULL DEFAULT 2')
  addColumn(this, 'runs', 'workflow_version', 'INTEGER NOT NULL DEFAULT 0')
  addColumn(this, 'runs', 'workspace_id', 'TEXT')
  addColumn(this, 'runs', 'final_report_delivered_at', 'TEXT')
  addColumn(this, 'runs', 'settled_at', 'TEXT')
  addColumn(this, 'runs', 'pause_reason', 'TEXT')
  addColumn(this, 'runs', 'cancel_reason', 'TEXT')
  addColumn(this, 'tasks', 'source_key', 'TEXT')
  addColumn(this, 'tasks', 'auto_options', "TEXT NOT NULL DEFAULT '{}'")
  addColumn(this, 'tasks', 'resolved_worktree_id', 'TEXT')
  addColumn(this, 'tasks', 'delivery', 'TEXT')
  addColumn(this, 'tasks', 'review_role', "TEXT NOT NULL DEFAULT 'normal'")
  addColumn(this, 'tasks', 'review_of_task_id', 'TEXT')
  addColumn(this, 'tasks', 'correction_round', 'INTEGER NOT NULL DEFAULT 0')
  addColumn(this, 'tasks', 'needs_coordinator_review', 'INTEGER NOT NULL DEFAULT 0')
  addColumn(this, 'tasks', 'code_version', 'TEXT')
  this.db.exec(`
    CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_run_source_key
      ON tasks(run_id, source_key) WHERE source_key IS NOT NULL;
    CREATE TABLE IF NOT EXISTS automatic_run_events (
      id            TEXT PRIMARY KEY,
      run_id        TEXT NOT NULL,
      task_id       TEXT,
      dispatch_id   TEXT,
      kind          TEXT NOT NULL,
      event_key     TEXT NOT NULL,
      payload       TEXT NOT NULL DEFAULT '{}',
      state         TEXT NOT NULL DEFAULT 'pending'
        CHECK(state IN ('pending', 'processed', 'failed')),
      attempts      INTEGER NOT NULL DEFAULT 0,
      created_at    TEXT NOT NULL DEFAULT (datetime('now')),
      processed_at  TEXT,
      UNIQUE(event_key)
    );
    CREATE INDEX IF NOT EXISTS idx_automatic_run_events_pending
      ON automatic_run_events(run_id, state, created_at);
    CREATE TABLE IF NOT EXISTS automatic_run_wakes (
      id            TEXT PRIMARY KEY,
      run_id        TEXT NOT NULL,
      event_id      TEXT NOT NULL,
      reason        TEXT NOT NULL,
      event_key     TEXT NOT NULL,
      status        TEXT NOT NULL DEFAULT 'queued'
        CHECK(status IN ('queued', 'delivered', 'suppressed')),
      message_id    TEXT,
      created_at    TEXT NOT NULL DEFAULT (datetime('now')),
      delivered_at  TEXT,
      UNIQUE(event_key)
    );
    CREATE INDEX IF NOT EXISTS idx_automatic_run_wakes_run
      ON automatic_run_wakes(run_id, status);
    CREATE TABLE IF NOT EXISTS task_deliveries (
      task_id       TEXT PRIMARY KEY,
      run_id        TEXT NOT NULL,
      dispatch_id   TEXT,
      outcome       TEXT NOT NULL CHECK(outcome IN ('succeeded', 'failed')),
      summary       TEXT NOT NULL DEFAULT '',
      evidence      TEXT NOT NULL DEFAULT '[]',
      handoff       TEXT,
      review_verdict TEXT CHECK(review_verdict IS NULL OR review_verdict IN ('approved', 'changes_requested')),
      code_version  TEXT,
      created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_task_deliveries_run ON task_deliveries(run_id);
  `)
}

function addColumn(db: OrchestrationDb, table: string, column: string, definition: string): void {
  if (!db.hasColumn(table, column)) {
    db.db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`)
  }
}
