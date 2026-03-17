import Database from "better-sqlite3";
import crypto from "crypto";

export function initDb(dbPath) {
  const db = new Database(dbPath);
  db.pragma("journal_mode = WAL");

  db.exec(`
    CREATE TABLE IF NOT EXISTS api_keys (
      id            INTEGER PRIMARY KEY AUTOINCREMENT,
      api_key_hash  TEXT    NOT NULL UNIQUE,
      client_name   TEXT    NOT NULL,
      monthly_limit INTEGER NOT NULL DEFAULT 100,
      renders_used  INTEGER NOT NULL DEFAULT 0,
      reset_month   TEXT    NOT NULL DEFAULT '',
      created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
      expires_at    TEXT
    );

    CREATE TABLE IF NOT EXISTS jobs (
      id              TEXT    PRIMARY KEY,
      api_key_hash    TEXT    NOT NULL,
      template_id     TEXT    NOT NULL,
      render_job_id   TEXT,
      request_id      TEXT,
      status          TEXT    NOT NULL DEFAULT 'queued',
      detail          TEXT    NOT NULL DEFAULT '',
      output_folder   TEXT    NOT NULL DEFAULT '',
      submitted_at    TEXT    NOT NULL DEFAULT (datetime('now')),
      completed_at    TEXT,
      job_payload     TEXT    NOT NULL DEFAULT '{}'
    );
  `);

  return db;
}

export function hashApiKey(apiKey) {
  return crypto.createHash("sha256").update(apiKey).digest("hex");
}

export function validateApiKey(db, apiKeyHash) {
  const row = db
    .prepare("SELECT * FROM api_keys WHERE api_key_hash = ?")
    .get(apiKeyHash);
  if (!row) return null;

  if (row.expires_at && new Date(row.expires_at) < new Date()) return null;

  // Reset monthly counter if we're in a new month
  const currentMonth = new Date().toISOString().slice(0, 7); // "YYYY-MM"
  if (row.reset_month !== currentMonth) {
    db.prepare(
      "UPDATE api_keys SET renders_used = 0, reset_month = ? WHERE id = ?"
    ).run(currentMonth, row.id);
    row.renders_used = 0;
    row.reset_month = currentMonth;
  }

  return row;
}

export function incrementUsage(db, apiKeyHash) {
  db.prepare(
    "UPDATE api_keys SET renders_used = renders_used + 1 WHERE api_key_hash = ?"
  ).run(apiKeyHash);
}
