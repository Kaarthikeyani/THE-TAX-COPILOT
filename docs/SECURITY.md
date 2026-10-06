# Security and privacy notes

What the code does:

* **Accounts.** You sign in with a mobile number and a one-time code (6 digits, 5 minutes, single use, 5 tries, 3 codes per number per 10 minutes, 30-second cooldown).
  Codes and session tokens are stored only as SHA-256 hashes. Sessions last 30 days, are revoked on sign-out, and every route except `/health`, login and the SMS webhook needs one.
* **Every person's data is separate.** Each user-owned table carries a `user_id`. The database layer (`app/database.py`) adds `WHERE user_id = <you>` to every read,
  update and delete and stamps every new row; a write with no user is refused. A guess at another person's record id returns 404. Tests prove this for reads, aggregates, bulk deletes, rules, events and metrics (`tests/test_accounts.py`).
* **Phone key.** Each account has its own private key for the SMS forwarder (`X-API-Key` on `/sms/webhook` only). It can post messages to that account and nothing else; it cannot read data.
  Stored hashed (lookup) and encrypted (so the Connect page can show it). Rotating it stops the old one immediately.
* **OTP delivery.** `COPILOT_OTP_PROVIDER` = `console` (default: the code is printed in the server window), `twilio`, or `webhook` (any SMS gateway). `COPILOT_DEV_OTP=1` also returns the code to the browser; the server refuses to start with it on a network address.
* Listens on `127.0.0.1` by default. Host-header allow-list (blocks DNS-rebinding; extend with `COPILOT_ALLOWED_HOSTS`), 512 KB body cap, rate limits (login 12/min, assistant 10/min, webhook 60/min, API 600/min per address),
  lockout after 10 failed keys or tokens in 5 minutes (webhook and app are counted separately, so a broken forwarder cannot lock you out of the app), CORS off unless `COPILOT_CORS_ORIGINS` is set.
* Validation errors never echo what you sent. Logs never contain raw SMS, phone numbers, codes or keys. Raw SMS is encrypted at rest (Fernet).
* **The shared ML model never trains on anyone's private data.** Your corrections become rules on your own account only.
* **The assistant** sends only computed totals (never merchant names or message text) to a model running on this computer (Ollama). Every figure in its reply is checked against those totals.
* **Delete my account** erases the account and every row it owns, plus its entries in the signals log. User ids are never reused.
* Static files are revalidated on every load so an upgrade cannot leave a browser on old scripts.
* Secrets (`secret.key`, the database, backups) are in `.gitignore`.

What it does not do:

* **No TLS.** Put a reverse proxy (Caddy, nginx, a tunnel) in front before using it off a network you trust. Sign-in codes and sessions travel in clear over plain HTTP.
* Phone-number login proves control of a number, not identity. SIM-swap attacks apply, as with any SMS code. No second factor, no device list, no audit trail.
* Rate limits and the live-push hub are in-process: run a single worker.
* Amounts, dates, merchants and categories are stored unencrypted (so the app can compute with them). Use disk encryption (BitLocker / FileVault).
* The consent screen is a demonstration of an Account Aggregator style flow; it is not connected to a real aggregator.
* This has not had an independent security review. Do not read the above as a guarantee.
