# Database, backup, restore, keys

* **Location:** `backend/data/copilot.db` (SQLite). Override the folder with `COPILOT_DATA_DIR`. Encryption key: `data/secret.key`
  (or the `COPILOT_SECRET_KEY` environment variable, which wins if set). Both are git-ignored.
* **What is encrypted:** the raw SMS text (Fernet, field level). Amounts, dates, merchants and categories are stored in clear so the app can compute with them.
  Anyone who can read the `data` folder can read those fields, so rely on disk encryption (BitLocker / FileVault) for the rest.
* **Upgrades keep your data.** On start-up `migrate()` adds any missing columns/tables/indexes. If columns are missing it first copies the database to `data/backups/`.
  It never drops or rewrites existing rows.
* **Backup:** `python -m app.maintenance backup` (uses SQLite's online backup API, safe while the server runs). Copy `data/backups/` somewhere off this machine
  **together with the key** - a backup without its key cannot show the original SMS text.
* **Restore:** stop the server, `python -m app.maintenance restore data/backups/<file>.db`. The current database is saved first.
* **Key lost or changed:** the app still works, but old messages show as "unreadable" (the original text cannot be recovered; parsed fields remain).
  `python -m app.maintenance key-check` tells you whether the current key can decrypt what is stored. Never generate a new key while old data matters.
* **Reset everything:** stop the server and delete `data/copilot.db` (keep a backup). Demo rows are removable on their own with "Remove demo data".
* **Accounts.** The `users` table holds one row per phone number; `otp_challenges` and `auth_sessions` hold hashed codes and tokens. Every other table has a `user_id`
  that the database layer filters and stamps automatically. A database from before accounts is upgraded in place: its rows have no owner until the first person signs in, who inherits them.
  `merchant_rules` is rebuilt once to make the unique key per user (rows are copied unchanged). User ids are never reused.
* **Backups hold everyone's data** (all accounts) and need the same key file.
