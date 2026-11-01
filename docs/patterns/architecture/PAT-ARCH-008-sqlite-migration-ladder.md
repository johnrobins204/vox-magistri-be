---
id: PAT-ARCH-008
category: architecture
status: accepted
supersedes: null
superseded_by: null
---

# Schema migrations: an ordered `user_version` ladder in the store constructor

## Problem
PAT-ARCH-002 rule 5 says "bump N and add a small ALTER branch", but there was no ALTER path
until REQ-0020. Today the constructor sets `PRAGMA user_version = 1` unconditionally. The
human's real `dnd.db` must survive each schema change. Several requirements in a row each
add a column (REQ-0020 `character`, REQ-0021 summary). Scattered `if version < N` branches
would make the order of steps and their idempotency easy to get wrong.

## Context
Use this for additive changes to a stdlib-`sqlite3` store (PAT-ARCH-002), such as new
nullable columns, tables or indexes. Do not use it for data rewrites, column drops or type
changes. Those need an ADR, and possibly the SQLAlchemy escape hatch named in PAT-ARCH-002.
This is not a migration framework: it is one module-level list and one loop. Introduced by
ADR-0008. There are two concrete call sites: v2 (REQ-0020) and v3 (REQ-0021).

## Solution
1. **The base schema stays frozen at v1.** The existing `CREATE TABLE/INDEX IF NOT EXISTS`
   statements keep their v1 shape. Never edit them to add a column.
2. **One ordered list:** `_MIGRATIONS: list[tuple[int, str, str, str]]` holds
   `(version, table, column, ddl)`, for example
   `(2, "sessions", "character", "ALTER TABLE sessions ADD COLUMN character TEXT")`. Each
   entry appends, versions strictly increase, and existing entries are never edited.
3. **Apply on open, under the store lock, before restart recovery:**
   - Read `PRAGMA user_version`.
   - Make sure the version is at least 1 after the base `CREATE`s.
   - For each entry with `version > current`, open an explicit transaction (`BEGIN`). Skip
     the DDL if `PRAGMA table_info(table)` already lists the column, so a step can be run
     again safely. Otherwise run the DDL. Then set `PRAGMA user_version = version` and
     commit.
4. **Never downgrade.** If the database's version is higher than the newest entry, log a
   WARNING via `get_logger` and leave the version alone.
5. **Log** `store.migrated` with `{from, to}` only. Do not log SQL with values.
6. **Test each step** with an old-version file DB built with raw `sqlite3`. Assert that
   existing rows survive, the new column reads as its default, `user_version` is the
   newest version, and that reopening the DB is a no-op. A fresh `:memory:` store must
   also reach the newest version.

## Consequences
- An existing `dnd.db` upgrades in place on startup, and new requirements add one tuple
  each.
- Only additive changes are covered. Anything else needs an ADR.
- The `table_info` guard protects against Python `sqlite3`'s implicit-transaction handling
  of DDL.

## Examples
- Planned: `SqliteSessionStore` v2 `sessions.character` (ADR-0008, REQ-0020), and v3, the
  REQ-0021 summary column.
