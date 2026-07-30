#!/usr/bin/env node
// Auto-applies SQL migrations during Vercel build.
// Requires POSTGRES_URL_NON_POOLING (injected by Supabase Vercel Integration).
// Skips silently when env var absent (local dev, CI).

import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import pg from "pg";

const connectionString = process.env.POSTGRES_URL_NON_POOLING;
if (!connectionString) {
  console.log("[auto-migrate] POSTGRES_URL_NON_POOLING not set — skipping.");
  process.exit(0);
}

const migrationsDir = join(process.cwd(), "supabase", "migrations");
let files;
try {
  files = (await readdir(migrationsDir)).filter((f) => f.endsWith(".sql")).sort();
} catch {
  console.log("[auto-migrate] No supabase/migrations/ directory — skipping.");
  process.exit(0);
}
if (files.length === 0) {
  console.log("[auto-migrate] No migration files — skipping.");
  process.exit(0);
}

const client = new pg.Client({ connectionString, ssl: { rejectUnauthorized: false } });
try {
  await client.connect();
  await client.query(`
    CREATE TABLE IF NOT EXISTS _auto_migrations (
      name TEXT PRIMARY KEY,
      applied_at TIMESTAMPTZ DEFAULT now()
    )
  `);
  const { rows } = await client.query("SELECT name FROM _auto_migrations ORDER BY name");
  const applied = new Set(rows.map((r) => r.name));

  let count = 0;
  for (const file of files) {
    if (applied.has(file)) continue;
    const sql = await readFile(join(migrationsDir, file), "utf-8");
    console.log(`[auto-migrate] Applying: ${file}`);
    await client.query("BEGIN");
    try {
      await client.query(sql);
      await client.query("INSERT INTO _auto_migrations (name) VALUES ($1)", [file]);
      await client.query("COMMIT");
      count++;
    } catch (err) {
      await client.query("ROLLBACK");
      console.error(`[auto-migrate] FAILED on ${file}: ${err.message}`);
      process.exit(1);
    }
  }
  console.log(`[auto-migrate] Done. Applied ${count} new, ${applied.size} already applied.`);
} finally {
  await client.end();
}
