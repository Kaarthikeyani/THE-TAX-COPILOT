# Compliance & launch-readiness checklist (honest status)

> Note: the evaluation section of this checklist predates v2. See README.md (feature status table) and docs/ for current behaviour.

| Area | Status | Notes |
|---|---|---|
| Encryption at rest | Done (mini scale) | Raw SMS stored as Fernet ciphertext; key in `data/secret.key` or `COPILOT_SECRET_KEY`. Not SQLCipher; the rest of the DB is plain SQLite. |
| Privacy of events | Done | Event stream carries category, section and amount range only. |
| Consent lifecycle | Demo | Grant / revoke / list with an AA-style artifact. Not a live Account Aggregator (Setu/Finvu) integration. |
| Authentication | Not done | Single local user, no login. Add auth before any multi-user use. |
| Tax rules | Partial | New/old regime slabs, 87A, cess. No surcharge, HRA, capital gains, or presumptive schemes. Rules need yearly review. Income-tax Act 2025 renumbers sections from 1 April 2026. |
| ML classifier | Demo | Small TF-IDF + logistic regression model; always show confidence and let the user correct. |
| Load testing | Informative | `python load_test.py` on one machine with SQLite. |
| Penetration test | Not done | Required before launch. |
| Advice disclaimer | Done | Shown in the UI; the app is decision support, not tax advice. |
