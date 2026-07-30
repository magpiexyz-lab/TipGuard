---
assumes: []
packages:
  runtime: [better-sqlite3]
  dev: ["@types/better-sqlite3"]
files:
  - src/lib/db.ts
env:
  server: []
  client: []
ci_placeholders: {}
clean:
  files: []
  dirs: []
gitignore: []
---
# Database: SQLite
> Used when experiment.yaml has `stack.database: sqlite`
> Assumes: nothing (framework-agnostic — works with any Node.js framework)

## Packages
```bash
npm install better-sqlite3
npm install -D @types/better-sqlite3
```

## Files to Create

### `src/lib/db.ts` — Database singleton with migration runner
```ts
import Database from "better-sqlite3";
import fs from "fs";
import path from "path";

const DB_PATH = process.env.DATABASE_PATH || "data/app.db";

// Ensure the data directory exists
const dir = path.dirname(DB_PATH);
if (!fs.existsSync(dir)) {
  fs.mkdirSync(dir, { recursive: true });
}

const db = new Database(DB_PATH);

// Enable WAL mode for better concurrent read performance
db.pragma("journal_mode = WAL");
db.pragma("foreign_keys = ON");

// Migration runner — applies numbered SQL files from migrations/
function runMigrations() {
  db.exec(`
    CREATE TABLE IF NOT EXISTS _migrations (
      name TEXT PRIMARY KEY,
      applied_at TEXT DEFAULT (datetime('now'))
    )
  `);

  const applied = new Set(
    db.prepare("SELECT name FROM _migrations").all().map((r: { name: string }) => r.name)
  );

  const migrationsDir = path.join(process.cwd(), "migrations");
  if (!fs.existsSync(migrationsDir)) return;

  const files = fs.readdirSync(migrationsDir)
    .filter((f) => f.endsWith(".sql"))
    .sort();

  for (const file of files) {
    if (applied.has(file)) continue;
    const sql = fs.readFileSync(path.join(migrationsDir, file), "utf8");
    db.exec(sql);
    db.prepare("INSERT INTO _migrations (name) VALUES (?)").run(file);
    console.log(`Applied migration: ${file}`);
  }
}

runMigrations();

export default db;
```
- Singleton pattern — import `db` wherever needed
- WAL mode for concurrent read performance (writes are serialized by SQLite)
- Foreign keys enabled by default
- Migrations auto-applied on first import (app startup)
- `DATABASE_PATH` defaults to `data/app.db` — configurable via env var

## Schema Management

SQL migrations go in `migrations/` as numbered files:
```
migrations/
  001_initial.sql
  002_add_indexes.sql
```

### Migration Conventions
- Use `CREATE TABLE IF NOT EXISTS` for idempotent migrations
- Every table should have:
  - `id INTEGER PRIMARY KEY AUTOINCREMENT`
  - `created_at TEXT DEFAULT (datetime('now'))`
- Use standard SQL types: `TEXT`, `INTEGER`, `REAL`, `BLOB`
- Add SQL comments explaining each table's purpose

### Example Migration
```sql
-- 001_initial.sql
-- Short URLs table for the URL shortener service

CREATE TABLE IF NOT EXISTS short_urls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  short_code TEXT UNIQUE NOT NULL,
  original_url TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_short_urls_code ON short_urls(short_code);
```

## Usage in Route Handlers
```ts
import db from "@/lib/db";

// Query
const rows = db.prepare("SELECT * FROM short_urls WHERE short_code = ?").get(code);

// Insert
const result = db.prepare(
  "INSERT INTO short_urls (short_code, original_url) VALUES (?, ?)"
).run(code, url);

// Transaction
const insertMany = db.transaction((items: { code: string; url: string }[]) => {
  const stmt = db.prepare("INSERT INTO short_urls (short_code, original_url) VALUES (?, ?)");
  for (const item of items) {
    stmt.run(item.code, item.url);
  }
});
insertMany(items);
```

- `better-sqlite3` is synchronous — no `await` needed
- Use `.get()` for single row, `.all()` for multiple rows, `.run()` for mutations
- Use transactions for batch operations
- Use prepared statements with `?` placeholders — never interpolate user input into SQL

## Access Control

SQLite does not have Row-Level Security. Enforce access control in route handlers:
- Validate the requesting user before queries (when `stack.auth` is present)
- Filter queries with `WHERE user_id = ?` for user-owned data
- Never expose admin queries to unauthenticated routes

## Portability

The schema is written in portable SQL to ease future migration to Postgres:
- Use `TEXT` instead of `VARCHAR` (both work in Postgres)
- Use `INTEGER` instead of `INT` (both work in Postgres)
- Avoid SQLite-specific functions (`datetime('now')` → replace with `NOW()` in Postgres)
- `AUTOINCREMENT` → replace with `SERIAL` or `gen_random_uuid()` in Postgres

## .gitignore Additions
Add the database file to `.gitignore` — it should not be committed:
```
data/
*.db
*.db-wal
*.db-shm
```

## Testing

For tests, use an in-memory database or a temporary file:
```ts
// tests/helpers/test-db.ts
import Database from "better-sqlite3";

export function createTestDb() {
  const db = new Database(":memory:");
  db.pragma("foreign_keys = ON");
  // Apply migrations to in-memory DB
  // ...
  return db;
}
```

## Patterns
- Import `db` from `@/lib/db` — singleton, auto-migrated on startup
- Synchronous API — no `async/await` needed for database calls
- Use prepared statements with `?` placeholders for all queries
- Use transactions for multi-step mutations
- WAL mode for concurrent reads during API request handling
- Database file lives in `data/` directory (gitignored)

## PR Instructions
- The SQLite database is created automatically on first run — no setup needed
- Run `npm run dev` and the database will be initialized with migrations
- Database file is gitignored — each environment has its own database

## Deploy Interface

Standardized subsections referenced by deploy.md and teardown.md. Each subsection is a self-contained recipe — deploy.md reads them by name and executes the instructions.

### Prerequisites

None — SQLite requires no external CLI or authentication.

### Config Gathering

None — SQLite has no external service to configure.

### Provisioning

None — SQLite database is auto-created on application startup when `db.ts` is first imported. No cloud provisioning step needed.

### Hosting Requirements

- **incompatible_hosting:** `[vercel]`
- **reason:** Serverless functions have no persistent filesystem — SQLite database files are lost between invocations
- **volume_config:**
  - `needed: true`
  - `mount_path: "/data"`
  - `env_vars: { "DATABASE_PATH": "/data/app.db" }`

### Teardown

None — SQLite database lives on the hosting provider's volume. Volume cleanup is handled by the hosting provider's teardown (deleting the project removes the volume).

### Manifest Keys

```json
{
  "provider": "sqlite"
}
```
