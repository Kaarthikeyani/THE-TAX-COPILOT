# Tax & Cash-Flow Co-Pilot (v3)

Reads bank SMS, sorts them into tax categories, estimates your tax (old vs new regime), and plans **month by month** how much is
safe to invest after reserving tax and keeping a cash buffer. Sign in with your phone number; new messages from your phone appear live.
FastAPI + SQLite backend that also serves the responsive web app: **one command, one port.**
Decision support, not tax or investment advice.

## Run it

You need Python 3.10+ (developed on 3.13). The backend serves the frontend; there is no separate frontend server or build step.

```
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

(macOS / Linux: `python3 -m venv .venv && source .venv/bin/activate`.) If PowerShell blocks the activate script: `Set-ExecutionPolicy -Scope Process Bypass`.

Open http://127.0.0.1:8811 and **sign in with your mobile number**. The 6-digit code is printed in the window running `python run.py`
(set `COPILOT_DEV_OTP=1` to also show it on the login screen while testing locally). To have codes texted for real, set `COPILOT_OTP_PROVIDER=twilio`
(`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`) or `webhook` (`COPILOT_OTP_WEBHOOK_URL`, works with any SMS gateway). See `app/auth.py`.
A new account starts empty; use "Try with demo data" to look around, "Remove demo data" to clear it.
An older single-user database is upgraded in place and its data goes to the first account that signs in.

The Ask page uses a local model through [Ollama](https://ollama.com) if one is installed (`ollama pull llama3.1`; any installed model works, or set `COPILOT_LLM_MODEL`). Without it, answers use fixed rules and say so.

Tests: `pip install -r requirements-dev.txt` then `cd backend && python -m pytest` (107 tests, about 30 seconds).

## Connect your phone (live SMS)

Build the small Android app once (`cd android && python build.py`, needs the Android SDK and a JDK), then open **Connect phone** in the web app: download the APK,
copy the setup code, paste it in the phone app. Messages then appear in Activity within seconds, with a "Live" light and a notice. See `docs/SMS_FORWARDER.md`.
iPhone cannot read SMS, so use paste there.

## How data flows

```
 Android forwarder ──POST /sms/webhook (your private key)──┐       (manual paste ► POST /sms/ingest, signed in)
                                                           ▼
 app/http_security.py  host check, size cap, rate limits          app/auth.py  phone + code login, sessions, per-user key
                                                           ▼
 app/parser.py         amount, debit/credit, merchant, date, balance   (OTP / failed / promo ► ignored)
                                                           ▼
 app/planner.py        dedupe ► classify:  your rules ► taxonomy + user_rules.csv ► keywords ► ML ► "uncategorized"
                         (classifier.py, merchant_memory.py, ml_classifier.py, model_registry.py)
                                                           ▼
 SQLite  data/copilot.db   every row owned by a user_id, enforced in app/database.py; raw SMS encrypted (security.py)
                                                           ▼
 app/live.py           pushes the new message to that user's open tabs (Server-Sent Events, GET /stream)
 app/regime_engine.py  old/new tax, rebate, surcharge, cess ──┐
 app/monthly_planner.py  12-month cash, advance tax, safe-to-invest ◄┘   (multi_period_optimizer.py = quarterly view)
 app/metrics.py        accuracy / precision / recall on YOUR checked messages        app/assistant.py  grounded Ask answers
                                                           ▼
 android/  plain-Java SMS forwarder (build.py makes the APK)   app/main.py  JSON API  ──►  frontend/ (index.html, app.js, account.js, monthly.js, accuracy.js, styles.css, v3.css) served at /
```

| If you want to change… | open |
|---|---|
| how an SMS is read | `backend/app/parser.py` |
| categories / merchants | `backend/data/*.csv`, `merchant_taxonomy.json` (see `docs/DATA_AND_RULES.md`) |
| tax rules | `backend/app/regime_engine.py` (`docs/TAX_RULES.md`) |
| the monthly plan maths | `backend/app/monthly_planner.py` |
| login / sessions / OTP delivery | `backend/app/auth.py` |
| an API route | `backend/app/main.py` |
| a screen | `frontend/app.js`, `account.js` (login, Connect, Ask), `monthly.js`, `accuracy.js` |
| model comparison | `backend/experiments/` |

## What is real and what is not

| Feature | Status | Verified by |
|---|---|---|
| Phone-number + one-time-code sign-in, revocable sessions | **Works.** Codes print in the server window by default; Twilio / webhook delivery is coded but **not tested against a live gateway** | `tests/test_accounts.py` |
| Each person's data is private (reads, writes, deletes, aggregates, rules, events, metrics) | **Works**, enforced in one place | `tests/test_accounts.py`, with two users on one server |
| Manual SMS paste -> parse -> classify -> store | **Works** | API tests, UI run |
| `POST /sms/webhook` with a per-user key (batch, duplicates, per-message errors, rate limit) | **Works server-side**, exercised with `curl`, the Connect page test button and tests | API tests |
| Live push of new messages to the open page | **Works** (verified in a browser: messages posted from outside appeared with no reload) | tests + browser run |
| Reading SMS from the phone | **Android app included** (`android/`). Tested on an Android 15 emulator: live delivery in about 3 s, personal texts and OTPs stay on the phone, offline queue retries on its own, inbox import without duplicates. **Not tested on a physical phone.** iPhone: not possible | `docs/SMS_FORWARDER.md`, emulator run |
| Category correction that persists and teaches **your** account | **Works**; never touches other users or the shared model | tests |
| Accuracy / precision / recall on **your real messages** (press "Looks right" or fix) | **Works**, with sample size and 95% interval; reads low if you only fix wrong ones | tests, browser run |
| Accuracy on the benchmark | Measured on **SYNTHETIC** data only (12 models); not the accuracy you will get on real SMS | `experiments/`, Accuracy page |
| Ask page (local LLM, answers checked against your numbers) | **Works** with Ollama (tested with `gemma4`, 13-28 s per answer on this machine); falls back to fixed rules | tests, browser run |
| Old/new regime tax incl. rebate and surcharge | **Works**; FY2026-27 slabs from secondary sources, 44ADA unverified | 23 tests; `docs/TAX_RULES.md` |
| Month-by-month planner, advance tax, what-if, bills | **Works** | 18 tests, backtest (synthetic) |
| Responsive layout (phone, tablet, desktop) | Checked at 320, 375, 768 and 1440 px: no horizontal overflow on any page; bottom bar on phones | browser run |
| Installable as an app (PWA) | Manifest and service worker present; **install prompt not tested** | - |
| Schema-safe upgrades, backup/restore, key check | **Works** (incl. the old single-user database) | tests, `docs/DATABASE.md` |
| TLS, hosting, account aggregator / bank APIs, iOS app, app-store release | **Not implemented** | - |

## Try each connection yourself

1. Sign in, then Activity -> Add transaction -> paste an SMS, or Connect phone -> "Send a test message".
2. Webhook from a shell: copy your key from Connect phone and follow `docs/SMS_FORWARDER.md` ("Test it from your computer").
3. Plan: the Monthly plan page. Interactive API docs: http://127.0.0.1:8811/docs (log in via `POST /auth/otp/request` and `/auth/otp/verify`, then Authorize with the token).
4. Experiments: `cd backend && python experiments/run_experiments.py` (about 20-30 minutes; `--quick` is faster), then `python experiments/planner_backtest.py`.

## Documents

`docs/SMS_FORWARDER.md`, `docs/DATABASE.md`, `docs/SECURITY.md`, `docs/TAX_RULES.md`, `docs/DATA_AND_RULES.md`, `docs/BASE_PAPER_COMPARISON.md`, `REPORT_GUIDE.md`, `backend/COMPLIANCE_CHECKLIST.md`.
Base paper: Suganya et al., ICDSBS 2025 (regresses savings, MAE 0.1008, RMSE 0.1418, R2 0.4141); this project solves a different problem, so numbers are not directly comparable. The comparison is on the Accuracy page and in `docs/BASE_PAPER_COMPARISON.md`.

## Demo mode (fake data, safe to show many people)

`COPILOT_DEMO=1 python run.py` turns the app into a walk-through with **fake everything**:

- **Fake sign-in.** Type any 3-12 digit number, tap the on-screen code (123456). A new number opens a short profile form (name, work, salary, loans,
  investments, savings) and gets fake bank messages built from those answers. The same number later returns to the same person.
  Numbers **111** (Priya, salaried, home loan) and **222** (Arjun, freelancer) always exist for a quick start.
- **Switched off:** real phone login, the SMS webhook and the Connect phone page. Each number is its own sandbox; sandboxes are deleted after 24 hours
  (`COPILOT_DEMO_HOURS`, not 111/222) and capped at 300 (`COPILOT_DEMO_MAX`).
- **AI chat.** Set `GEMINI_API_KEY` (free, from aistudio.google.com) or `ANTHROPIC_API_KEY` (server side only) and the Ask page uses that AI to reason over the person's figures, with conversation memory and a
  "How I worked this out" panel. Model: `COPILOT_AI_MODEL` (default `claude-sonnet-5-5`). Cost guard: `COPILOT_AI_DAILY_CAP` answers a day (default 300).
  Without a key it falls back to a local Ollama model, then to fixed rules. Voice input uses the browser's own speech-to-text (Chrome, Edge, Android).

To host it: push to GitHub, then **New > Blueprint** on [Render](https://render.com) (reads `render.yaml`) and add `ANTHROPIC_API_KEY` in the dashboard.
Data is not kept across restarts (free tier), which is fine for a demo. See `app/demo_mode.py` and `app/assistant.py`.

## Language-model tier for classification (optional)

`COPILOT_LLM_CLASSIFY=1` lets a language model (Gemini, Claude or a local Ollama model) classify merchants the ML model is unsure of, fused with the ML
probabilities. On unseen merchants (synthetic) accuracy goes 69.8% -> 82.4%. See `app/llm_classifier.py` and `experiments/hybrid_fusion.py`. Only the merchant
text and direction are sent. Off by default.
