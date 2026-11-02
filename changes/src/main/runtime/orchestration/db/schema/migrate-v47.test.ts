import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { afterEach, describe, expect, it } from 'vitest'
import { SCHEMA_VERSION } from '../contract-constants'
import { OrchestrationDb } from '../orchestration-db'

const directories: string[] = []

afterEach(() => {
  for (const directory of directories.splice(0)) {
    rmSync(directory, { recursive: true, force: true })
  }
})

function legacyV46Database(): string {
  const directory = mkdtempSync(join(tmpdir(), 'orca-v47-migration-'))
  directories.push(directory)
  const file = join(directory, 'orchestration.db')
  const raw = new DatabaseSync(file)
  raw.exec(`
    CREATE TABLE runs (
      id TEXT PRIMARY KEY,
      objective TEXT NOT NULL,
      home_database TEXT NOT NULL DEFAULT 'this_database',
      coordinator_handle TEXT,
      coordinator_pane_key TEXT,
      coordinator_orca_session_id TEXT,
      coordinator_orca_session_id_generation INTEGER,
      consumer_generation INTEGER NOT NULL DEFAULT 0,
      legacy INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE tasks (
      id TEXT PRIMARY KEY,
      run_id TEXT NOT NULL DEFAULT 'legacy',
      parent_id TEXT,
      created_by_terminal_handle TEXT,
      created_by_pane_key TEXT,
      created_by_process_incarnation TEXT,
      created_by_run_generation INTEGER,
      task_title TEXT,
      display_name TEXT,
      spec TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      deps TEXT NOT NULL DEFAULT '[]',
      result TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      completed_at TEXT
    );
    INSERT INTO runs (id, objective, coordinator_handle)
      VALUES ('run_old', 'manual work', 'term_coord');
    INSERT INTO tasks (id, run_id, spec, status)
      VALUES ('task_old', 'run_old', 'old task', 'ready');
    PRAGMA user_version = 46;
  `)
  raw.close()
  return file
}

describe('migrateV47', () => {
  it('adds automatic-run columns and tables while keeping existing Runs manual', () => {
    const file = legacyV46Database()
    const db = new OrchestrationDb(file)
    try {
      expect(db.db.pragma('user_version', { simple: true })).toBe(SCHEMA_VERSION)
      expect(db.getRun('run_old')).toMatchObject({
        execution_mode: 'manual',
        execution_state: null,
        max_parallel: 2,
        workflow_version: 0
      })
      expect(db.getTask('task_old')).toMatchObject({
        source_key: null,
        auto_options: '{}',
        review_role: 'normal',
        correction_round: 0,
        needs_coordinator_review: 0
      })
      expect(db.listPendingAutomaticRunEvents('run_old')).toEqual([])
      expect(db.listPendingGatesForRun('run_old')).toEqual([])
    } finally {
      db.close()
    }
  })

  it('is idempotent when reopened', () => {
    const file = legacyV46Database()
    const first = new OrchestrationDb(file)
    first.close()
    const second = new OrchestrationDb(file)
    try {
      expect(second.db.pragma('user_version', { simple: true })).toBe(SCHEMA_VERSION)
      expect(second.getRun('run_old')?.execution_mode).toBe('manual')
    } finally {
      second.close()
    }
  })
})
